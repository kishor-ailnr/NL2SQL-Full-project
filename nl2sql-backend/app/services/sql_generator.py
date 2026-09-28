import copy
import difflib
import hashlib
import json
import logging
import re
import time
import warnings
from typing import Dict, Any, Optional, List, Union, Tuple
from app.config import GEMINI_API_KEY
from app.services.session_store import get_session

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import google.generativeai as genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

# Configure Gemini client if API key is present
if GEMINI_API_KEY and genai:
    genai.configure(api_key=GEMINI_API_KEY, transport="rest")

# Prioritized list of active Gemini models (fastest and available first)
MODELS_TO_TRY = [
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
]

# Sticky working model pointer to avoid fallback delays on every call
_WORKING_MODEL: str = "gemini-3.1-flash-lite"

# ---------------------------------------------------------------------------
# In-Memory Response Caching (TTL: 10 minutes)
# Key: SHA-256(schema_signature + normalized_question + language)
# Value: {"response": Dict[str, Any], "created_at": float}
# ---------------------------------------------------------------------------
_QUERY_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS: float = 600.0  # 10 minutes


def _compute_schema_signature(session: Optional[Dict[str, Any]]) -> str:
    """Compute a deterministic signature of the session's database schema."""
    if not session:
        return "no_session"
    schema = session.get("schema", {})
    tables = session.get("tables", [])
    parts = []
    for tbl in sorted(schema.keys()):
        cols = schema[tbl]
        col_sigs = []
        for c in cols:
            if isinstance(c, dict):
                col_sigs.append(f"{c.get('name')}:{c.get('type')}")
            else:
                col_sigs.append(str(c))
        parts.append(f"{tbl}:({','.join(col_sigs)})")
    if not parts and tables:
        parts = [f"tables:{','.join(sorted(tables))}"]
    raw_sig = "|".join(parts) or "empty_schema"
    return hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:16]


def _generate_cache_key(schema_signature: str, question: str, language: str, context_sig: str = "") -> str:
    """Generate a deterministic SHA-256 cache key from schema, question, language, and context."""
    norm_q = " ".join(question.strip().lower().split())
    norm_lang = (language or "auto").strip().lower()
    raw = f"{schema_signature}::{norm_q}::{norm_lang}::{context_sig}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_from_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve entry from cache if present and not expired; evict on read if expired."""
    entry = _QUERY_CACHE.get(cache_key)
    if not entry:
        return None

    now = time.time()
    created_at = entry.get("created_at", 0)
    age = now - created_at

    if age > CACHE_TTL_SECONDS:
        # Expired: evict on read
        _QUERY_CACHE.pop(cache_key, None)
        logger.info(
            "[Cache EVICT] Evicted expired cache entry %s (age: %.1fs > %ds)",
            cache_key[:12],
            age,
            int(CACHE_TTL_SECONDS),
        )
        return None

    logger.info(
        "[Cache HIT] Reusing cached Gemini response for key %s (age: %.1fs, TTL: %ds)",
        cache_key[:12],
        age,
        int(CACHE_TTL_SECONDS),
    )
    return copy.deepcopy(entry["response"])


def _put_in_cache(cache_key: str, response_data: Dict[str, Any]) -> None:
    """Store full Gemini response in the in-memory cache with current timestamp."""
    _QUERY_CACHE[cache_key] = {
        "response": copy.deepcopy(response_data),
        "created_at": time.time(),
    }
    logger.info(
        "[Cache STORE] Cached Gemini response for key %s (TTL: %ds)",
        cache_key[:12],
        int(CACHE_TTL_SECONDS),
    )


def clear_query_cache(session_id: Optional[str] = None) -> None:
    """Clear query cache globally or for a specific session."""
    count = len(_QUERY_CACHE)
    _QUERY_CACHE.clear()
    logger.info("[Cache CLEAR] Cleared %d cached response entries.", count)


def get_cache_size() -> int:
    """Return the number of entries currently stored in the query cache."""
    return len(_QUERY_CACHE)


def _clean_json_string(text: str) -> str:
    """Strip markdown fences and whitespace from model output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Match ```json ... ``` or ``` ... ```
        pattern = r"^```(?:json)?\s*(.*?)\s*```$"
        match = re.search(pattern, cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
        else:
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
    return cleaned


def _format_schema_for_prompt(schema: Dict[str, Any], sample_values_map: Optional[Dict[str, Any]] = None) -> str:
    """Format schema dictionary into readable text for the prompt, including sample values."""
    schema_lines = []
    for table, cols in schema.items():
        col_strs = []
        for c in cols:
            col_name = c.get("name", "")
            col_type = c.get("type", "")
            constraints = []
            if c.get("primary_key"):
                constraints.append("PRIMARY KEY")
            if c.get("nullable") is False:
                constraints.append("NOT NULL")
            constraints_str = f", {', '.join(constraints)}" if constraints else ""

            samples = c.get("sample_values")
            if not samples and sample_values_map and table in sample_values_map:
                samples = sample_values_map[table].get(col_name)
            samples = samples or []
            if samples:
                samples_str = ", ".join(repr(s) if isinstance(s, str) else str(s) for s in samples)
                if col_type:
                    col_strs.append(f"{col_name} ({col_type}{constraints_str}, sample values: {samples_str})")
                else:
                    col_strs.append(f"{col_name} (sample values: {samples_str}{constraints_str})")
            else:
                if col_type:
                    col_strs.append(f"{col_name} ({col_type}{constraints_str})")
                else:
                    col_strs.append(f"{col_name}{constraints_str}")
        schema_lines.append(f"Table '{table}': {', '.join(col_strs)}")
    return "\n".join(schema_lines)


def detect_input_language(text: str) -> str:
    """Detect whether user query is written in Tamil script, Thanglish, or English.
    
    Returns:
        'tamil': if text contains Unicode characters in Tamil block (\u0B80-\u0BFF).
        'thanglish': if text is Latin script containing common Tamil transliteration words/patterns.
        'english': otherwise.
    """
    if any("\u0b80" <= c <= "\u0bff" for c in text):
        return "tamil"

    thanglish_words = {
        "vayasuku", "vayasu", "mela", "keela", "irukra", "irukku", "irukkum",
        "kaatu", "kaatunga", "kudu", "kudunga", "pannu", "pannunga", "yaaru",
        "enna", "ethana", "eppadi", "eppa", "ellam", "ella", "maruthuvar", "noi",
        "noiyali", "noiyaligal", "thara", "solli", "paaru", "mattum", "inga", "enga",
        "oru", "rendu", "aana", "aachu", "romba", "mukkiyam", "mukkiyamaana", "periya",
        "chinna", "adutha", "munnadi", "pinnaadi", "epdi", "yenna", "yethana",
        "thanga", "konjam", "paakanum", "theriyum", "venum", "sollu", "sollunga"
    }
    tokens = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    if tokens.intersection(thanglish_words):
        return "thanglish"

    return "english"


def _enforce_language(data: Dict[str, Any], detected_lang: str, model: Optional[Any] = None) -> None:
    """Enforce language constraints on explanation and clarification_question."""
    data["detected_language"] = detected_lang
    if detected_lang == "thanglish":
        if data.get("explanation"):
            exp = data["explanation"].strip()
            if not (exp.startswith("Understood —") or exp.startswith("Understood -") or exp.startswith("Understood –")):
                data["explanation"] = f"Understood — {exp}"
        if data.get("clarification_question"):
            cq = data["clarification_question"].strip()
            if not (cq.startswith("Understood —") or cq.startswith("Understood -") or cq.startswith("Understood –")):
                data["clarification_question"] = f"Understood — {cq}"
    elif detected_lang == "tamil":
        # If explanation contains NO Tamil Unicode characters, translate to Tamil
        if data.get("explanation") and not any("\u0b80" <= c <= "\u0bff" for c in data["explanation"]):
            logger.warning("Gemini returned non-Tamil explanation for Tamil query; translating to Tamil...")
            if model:
                try:
                    t_resp = model.generate_content(
                        f"Translate this query explanation into natural Tamil script (தமிழ் எழுத்தில்). Return ONLY the Tamil translation without quotes or English:\n\n{data['explanation']}"
                    )
                    if t_resp.text and any("\u0b80" <= c <= "\u0bff" for c in t_resp.text):
                        data["explanation"] = t_resp.text.strip()
                except Exception as te:
                    logger.warning("Tamil translation fallback failed: %s", te)
            if not any("\u0b80" <= c <= "\u0bff" for c in (data.get("explanation") or "")):
                data["explanation"] = "இந்த வினவல் கொடுக்கப்பட்ட நிபந்தனையின் அடிப்படையில் தொடர்புடைய தரவை மீட்டெடுக்கிறது."

        # If clarification_question contains NO Tamil Unicode characters, translate to Tamil
        if data.get("clarification_question") and not any("\u0b80" <= c <= "\u0bff" for c in data["clarification_question"]):
            logger.warning("Gemini returned non-Tamil clarification_question for Tamil query; translating to Tamil...")
            if model:
                try:
                    t_resp = model.generate_content(
                        f"Translate this clarification question into natural Tamil script (தமிழ் எழுத்தில்). Return ONLY the Tamil translation without quotes or English:\n\n{data['clarification_question']}"
                    )
                    if t_resp.text and any("\u0b80" <= c <= "\u0bff" for c in t_resp.text):
                        data["clarification_question"] = t_resp.text.strip()
                except Exception as te:
                    logger.warning("Tamil clarification translation fallback failed: %s", te)
            if not any("\u0b80" <= c <= "\u0bff" for c in (data.get("clarification_question") or "")):
                data["clarification_question"] = "தயவுசெய்து உங்கள் கேள்வியை மேலும் தெளிவுபடுத்தவும்."


def get_core_person_name(name: str) -> str:
    """Normalize a person's name by stripping professional titles (Dr., Mr., Prof., etc.) and punctuation."""
    if not name or not isinstance(name, str):
        return ""
    cleaned = re.sub(r"^(?:dr|doctor|mr|mrs|ms|prof)\b\.?\s*", "", name.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:dr|doctor|mr|mrs|ms|prof)\b\.?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return " ".join(cleaned.lower().split())


def detect_multi_table_ambiguity(
    nl_question: str,
    schema: Optional[Dict[str, Any]] = None,
    sample_values_map: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Detect if a query references an entity name that exists across multiple tables (e.g.

    'James Wilson' in patients vs 'Dr. James Wilson' in doctors).

    Returns a dict with:
      - is_ambiguous: True if role/table is not specified or ambiguous
      - clarification_question: Question asking the user to choose
      - matching_tables: dict of {table: full_name}
      - core_name: normalized core name
      - target_table: (if not ambiguous) the table specified by the user
      - target_name: (if not ambiguous) the exact name in that table
    or None if no multi-table name match is found.
    """
    if not nl_question or not nl_question.strip():
        return None
    q_lower = nl_question.strip().lower()

    table_names_map: Dict[str, Dict[str, str]] = {}

    def _add_sample(tbl: str, col_name: str, val: Any) -> None:
        if "name" in col_name.lower() and isinstance(val, str) and len(val.strip()) >= 3:
            c_name = get_core_person_name(val)
            if len(c_name) >= 3:
                if c_name not in table_names_map:
                    table_names_map[c_name] = {}
                table_names_map[c_name][tbl] = val.strip()

    if sample_values_map:
        for tbl, cols in sample_values_map.items():
            for col, vals in (cols or {}).items():
                for v in vals or []:
                    _add_sample(tbl, col, v)

    if schema:
        for tbl, cols in schema.items():
            if isinstance(cols, list):
                for c in cols:
                    if isinstance(c, dict):
                        col_name = c.get("name", "")
                        for v in c.get("sample_values") or []:
                            _add_sample(tbl, col_name, v)

    multi_table_names = {c_name: tbls for c_name, tbls in table_names_map.items() if len(tbls) > 1}
    if not multi_table_names:
        return None

    q_clean = " " + re.sub(r"[^\w\s]", " ", q_lower) + " "
    q_words = set(re.findall(r"\b[a-zA-Z0-9_]+\b", q_lower))

    for c_name, tbls in multi_table_names.items():
        c_parts = c_name.split()
        if f" {c_name} " in q_clean or all(w in q_words for w in c_parts):
            has_patient = bool(re.search(r"\b(?:patient|patients|நோயாளி|நோயாளிங்க)\b", q_lower))
            has_doctor = bool(re.search(r"\b(?:doctor|doctors|dr|dr\.|மருத்துவர்)\b", q_lower))

            # If user explicitly specified "patient Dr. <name>" or "patient <name>"
            if has_patient and (not has_doctor or re.search(r"\bpatient(?:s)?\s+(?:dr\.?\s+)?" + re.escape(c_parts[0]), q_lower)):
                return {
                    "is_ambiguous": False,
                    "target_table": "patients",
                    "target_name": tbls.get("patients", c_name),
                    "core_name": c_name,
                    "matching_tables": tbls,
                }
            elif has_doctor and not has_patient:
                return {
                    "is_ambiguous": False,
                    "target_table": "doctors",
                    "target_name": tbls.get("doctors", c_name),
                    "core_name": c_name,
                    "matching_tables": tbls,
                }
            else:
                # Ambiguous: either both mentioned or neither mentioned
                detected_lang = detect_input_language(nl_question)
                doc_repr = tbls.get('doctors', 'Dr. ' + c_name)
                pat_repr = tbls.get('patients', c_name)
                if detected_lang == "tamil":
                    clarif_q = f"மருத்துவர் '{doc_repr}' மற்றும் நோயாளி '{pat_repr}' என இருவர் உள்ளனர். உங்களுக்கு யாருடைய விவரங்கள் வேண்டும் (மருத்துவர்/நோயாளி)?"
                else:
                    clarif_q = f"There is a doctor named '{doc_repr}' and a patient named '{pat_repr}'. Which one would you like details for (doctor/patient)?"
                return {
                    "is_ambiguous": True,
                    "clarification_question": clarif_q,
                    "matching_tables": tbls,
                    "core_name": c_name,
                }

    return None


def find_table_for_value(
    value: str,
    sample_values_map: Optional[Dict[str, Any]],
    schema: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Find which table contains the given value in its sample values or schema."""
    if not value or not isinstance(value, str):
        return None
    val_clean = re.sub(r"[^\w\s]", "", value.strip().lower())
    if not val_clean:
        return None

    if sample_values_map:
        for tbl, cols in sample_values_map.items():
            for col, vals in (cols or {}).items():
                for v in (vals or []):
                    if isinstance(v, str) and re.sub(r"[^\w\s]", "", v.strip().lower()) == val_clean:
                        return tbl

    if schema:
        for tbl, cols in schema.items():
            if isinstance(cols, list):
                for c in cols:
                    for v in (c.get("sample_values") or []):
                        if isinstance(v, str) and re.sub(r"[^\w\s]", "", v.strip().lower()) == val_clean:
                            return tbl
    return None


# ---------------------------------------------------------------------------
# Multi-Entity Conjunctions & Result Matching (AND / OR)
# ---------------------------------------------------------------------------

ATTRIBUTE_FILTER_KEYWORDS = {
    "age", "gender", "male", "female", "older", "younger", "above", "below",
    "greater", "less", "more", "between", "diagnosis", "disease", "condition",
    "diabetic", "diabetes", "hypertensive", "hypertension", "fever", "cancer",
    "admitted", "admission", "date", "status", "scheduled", "completed", "cancelled",
    "count", "average", "avg", "sum", "total", "top", "limit", "min", "max",
    "department", "salary", "price", "cost", "bill", "billing", "paid", "unpaid",
    "amount", "years", "year", "months", "month", "days", "day"
}

DISCARD_WORDS = {
    "the", "all", "details", "record", "records", "data", "info", "information",
    "show", "list", "get", "find", "view", "display", "check", "search"
}


def clean_entity_term(term: str) -> str:
    """Normalize and clean a candidate entity string from a conjunction clause."""
    t = term.strip()
    t = re.sub(r"^(?:details\s+of|records?\s+of|info\s+of|data\s+of)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^the\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^[^\w]+|[^\w]+$", "", t)
    return t.strip()


def extract_entity_conjunctions(nl_question: str) -> Optional[Dict[str, Any]]:
    """Detect natural language entity conjunctions (AND / OR) between multiple requested entities.

    Distinguishes entity conjunctions (e.g. 'patient 1 and patient 2', 'Alice & Bob',
    'patient A as well as patient B', 'A, B and C', 'patient 1 or patient 2')
    from boolean attribute filter conjunctions (e.g. 'diabetic and above 60', 'age > 50 and gender = female').

    Returns a dict with:
        operator: 'AND' | 'OR'
        entity_type: 'patient' | 'doctor' | 'customer' | 'product' | 'record'
        entities: list of clean entity strings
        original_query: str
    or None if the question is not a multi-entity query.
    """
    if not nl_question or not nl_question.strip():
        return None
    q = nl_question.strip()
    q_lower = q.lower()

    if ";" in q:
        return None

    # Reject queries with explicit comparison operators (attribute filters like age > 50)
    if re.search(r"[><=]|>=|<=", q):
        return None

    # Reject aggregation queries (e.g. "count of patients and count of doctors")
    if re.search(r"\b(?:count|average|avg|sum|total)\b", q_lower):
        return None

    # Standardize conjunction connectors
    normalized_q = re.sub(r"\b(?:as\s+well\s+as|along\s+with)\b", " and ", q, flags=re.IGNORECASE)
    normalized_q = re.sub(r"\s*&\s*", " and ", normalized_q)

    has_or = bool(re.search(r"\b(?:or)\b", normalized_q, flags=re.IGNORECASE))
    has_and = bool(re.search(r"\b(?:and)\b", normalized_q, flags=re.IGNORECASE))

    if not has_and and not has_or and "," not in normalized_q:
        return None

    if has_or and not has_and:
        op = "OR"
        split_pattern = r"\b(?:or)\b"
    else:
        op = "AND"
        split_pattern = r"\b(?:and)\b"

    prefix_pattern = r"^(?:give\s+(?:me\s+)?(?:the\s+)?(?:details|records?|data|info)?\s*(?:of)?|show\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:details|records?|data|info)?\s*(?:of)?|display|view|list|find|compare|search\s+for)\s*"
    stripped_q = re.sub(prefix_pattern, "", normalized_q.strip(), flags=re.IGNORECASE).strip()

    entity_type = "record"
    if re.search(r"\bpatients?\b", q_lower):
        entity_type = "patient"
    elif re.search(r"\bdoctors?\b", q_lower):
        entity_type = "doctor"
    elif re.search(r"\bcustomers?\b", q_lower):
        entity_type = "customer"
    elif re.search(r"\bproducts?\b", q_lower):
        entity_type = "product"

    parts = re.split(split_pattern, stripped_q, flags=re.IGNORECASE)
    raw_entities = []
    for p in parts:
        subparts = [sp.strip() for sp in p.split(",") if sp.strip()]
        raw_entities.extend(subparts)

    entities = []
    for raw in raw_entities:
        c = clean_entity_term(raw)
        if c:
            words = set(re.findall(r"\b\w+\b", c.lower()))
            if words.intersection(ATTRIBUTE_FILTER_KEYWORDS):
                return None
            if c.lower() not in DISCARD_WORDS and len(c) >= 1:
                entities.append(c)

    if len(entities) >= 2:
        return {
            "operator": op,
            "entity_type": entity_type,
            "entities": entities,
            "original_query": q,
        }
    return None


def fix_mutually_exclusive_and(sql: str) -> str:
    """Detect and convert mutually exclusive AND conditions on the same column to OR.

    e.g. WHERE name = 'Alice' AND name = 'Bob' -> WHERE name = 'Alice' OR name = 'Bob'
    e.g. WHERE LOWER(name) = 'alice' AND LOWER(name) = 'bob' -> WHERE LOWER(name) = 'alice' OR LOWER(name) = 'bob'
    e.g. WHERE id = 1 AND id = 2 -> WHERE id = 1 OR id = 2
    Preserves range conditions (e.g. age > 20 AND age < 50) and cross-column filters (diagnosis = 'X' AND age > 60).
    """
    if not sql or " AND " not in sql.upper():
        return sql

    pattern = r"((?:LOWER\s*\(\s*)?(\w+)(?:\s*\))?\s*=\s*(?:'[^']*'|\d+))\s+AND\s+((?:LOWER\s*\(\s*)?\2(?:\s*\))?\s*=\s*(?:'[^']*'|\d+))"
    current = sql
    for _ in range(5):
        new_sql = re.sub(pattern, r"\1 OR \3", current, flags=re.IGNORECASE)
        if new_sql == current:
            break
        current = new_sql
    return current


def match_entity_to_rows(entity: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Match a requested entity (by name, core name, or integer ID) to database rows."""
    matched = []
    e_clean = entity.strip().lower()
    e_core = get_core_person_name(entity)

    id_match = re.search(r"\b(\d+)\b", e_clean)
    target_id = int(id_match.group(1)) if id_match else None

    for row in rows:
        # Match by ID
        if target_id is not None and "id" in row:
            try:
                if int(row["id"]) == target_id:
                    matched.append(row)
                    continue
            except (ValueError, TypeError):
                pass

        # Match by name column
        row_matched = False
        for col, val in row.items():
            if "name" in col.lower() and isinstance(val, str):
                v_clean = val.strip().lower()
                v_core = get_core_person_name(val)
                if (
                    e_clean == v_clean
                    or (e_core and e_core == v_core)
                    or (len(e_core) >= 3 and e_core in v_clean)
                    or (len(v_core) >= 3 and v_core in e_clean)
                ):
                    matched.append(row)
                    row_matched = True
                    break
        if row_matched:
            continue

    return matched


def find_entity_candidate(entity: str, all_sample_names: List[str]) -> Optional[str]:
    """Find a fuzzy/near-miss candidate for an unavailable entity in known sample names."""
    e_clean = entity.strip().lower()
    e_core = get_core_person_name(entity)
    best_candidate = None
    best_score = 0.0

    for s_name in all_sample_names:
        s_clean = s_name.strip().lower()
        s_core = get_core_person_name(s_name)

        if e_clean == s_clean or (e_core and e_core == s_core):
            continue

        if e_core and s_core:
            sim = difflib.SequenceMatcher(None, e_core, s_core).ratio()
            if sim >= 0.75 and sim > best_score:
                best_score = sim
                best_candidate = s_name

        sim_full = difflib.SequenceMatcher(None, e_clean, s_clean).ratio()
        if sim_full >= 0.75 and sim_full > best_score:
            best_score = sim_full
            best_candidate = s_name

    return best_candidate if best_score >= 0.75 else None


def evaluate_multi_entity_results(
    conjunction_info: Dict[str, Any],
    exec_result: List[Dict[str, Any]],
    all_sample_names: List[str],
) -> Dict[str, Any]:
    """Evaluate database execution results against all requested entities independently.

    Provides complete partial success tracking, candidate matching, and structured explanations.
    """
    entities = conjunction_info.get("entities", [])
    operator = conjunction_info.get("operator", "AND")
    entity_type = conjunction_info.get("entity_type", "patient")

    entity_evaluations = []
    found_count = 0
    missing_count = 0

    for ent in entities:
        matched_rows = match_entity_to_rows(ent, exec_result) if exec_result else []
        if matched_rows:
            found_count += 1
            entity_evaluations.append({
                "entity": ent,
                "status": "FOUND",
                "rows": matched_rows,
                "candidate": None,
            })
        else:
            missing_count += 1
            cand = find_entity_candidate(ent, all_sample_names)
            entity_evaluations.append({
                "entity": ent,
                "status": "NOT_FOUND",
                "rows": [],
                "candidate": cand,
            })

    lines = []
    has_clarification = False
    clarification_question = None

    if found_count == len(entities):
        lines.append(f"Found matching details for all requested {entity_type}s:")
        for idx, ev in enumerate(entity_evaluations, 1):
            names = [r.get("name", ev["entity"]) for r in ev["rows"]]
            lines.append(f"{idx}. {ev['entity']}: Found ({', '.join(str(n) for n in names)})")
    elif found_count > 0:
        found_names = [ev["entity"] for ev in entity_evaluations if ev["status"] == "FOUND"]
        lines.append(f"I found data for {', '.join(found_names)}.")

        candidates_to_clarify = []
        for ev in entity_evaluations:
            if ev["status"] == "NOT_FOUND":
                if ev["candidate"]:
                    lines.append(f"For {ev['entity']}, I couldn't find an exact match. Possible match: '{ev['candidate']}'.")
                    candidates_to_clarify.append(f"Did you mean '{ev['candidate']}' for '{ev['entity']}'?")
                else:
                    lines.append(f"No matching data was found for {ev['entity']}.")

        if candidates_to_clarify:
            has_clarification = True
            clarification_question = " ".join(candidates_to_clarify) + " Would you like me to use this record?"
    else:
        candidates = [(ev["entity"], ev["candidate"]) for ev in entity_evaluations if ev["candidate"]]
        if candidates:
            has_clarification = True
            cand_phrases = [f"Did you mean '{c}' for '{e}'?" for e, c in candidates]
            clarification_question = " ".join(cand_phrases)
            lines.append(f"I couldn't find exact matches for the requested {entity_type}s.")
            for e, c in candidates:
                lines.append(f"- Possible match for '{e}': '{c}'")
        else:
            lines.append(f"No matching data was found for the requested {entity_type}s.")

    explanation = "\n\n".join(lines)

    return {
        "entity_evaluations": entity_evaluations,
        "found_count": found_count,
        "missing_count": missing_count,
        "total_count": len(entities),
        "explanation": explanation,
        "has_clarification": has_clarification,
        "clarification_question": clarification_question,
        "data_available": found_count > 0 or has_clarification,
    }


def find_near_miss_value(
    nl_question: str,
    schema: Optional[Dict[str, Any]],
    sample_values_map: Optional[Dict[str, Any]],
) -> Optional[tuple[str, str]]:
    """Detect if the user is searching for a value/name that has a genuine near-miss in sample values.

    Returns (literal_user_input, suggested_close_match) if a near-miss is found,
    or None if exact match exists or no close match exists.
    """
    if not nl_question or not nl_question.strip():
        return None

    # Multi-entity queries are handled post-execution to support partial success
    if extract_entity_conjunctions(nl_question):
        return None

    q_lower = nl_question.strip().lower()

    # Do not check near-miss for obvious criteria / aggregations / temporal filters
    criteria_keywords = {
        "day", "days", "month", "months", "year", "years", "week", "weeks",
        "older", "younger", "greater", "less", "more", "between", "visited",
        "admitted", "how many", "count", "average", "avg", "sum", "total",
        "highest", "lowest", "most", "least", "top"
    }
    q_words_set = set(re.findall(r"\b[a-zA-Z0-9_]+\b", q_lower))
    if q_words_set.intersection(criteria_keywords):
        return None

    # Collect distinct sample values from sample_values_map and schema
    all_samples = []
    if sample_values_map:
        for tbl, cols in sample_values_map.items():
            for col, vals in cols.items():
                is_name = "name" in col.lower()
                for v in vals or []:
                    if isinstance(v, str) and len(v.strip()) >= 3:
                        all_samples.append((v.strip(), is_name))
    if schema:
        for tbl, cols in schema.items():
            if isinstance(cols, list):
                for c in cols:
                    if isinstance(c, dict):
                        is_name = "name" in c.get("name", "").lower()
                        for v in c.get("sample_values") or []:
                            if isinstance(v, str) and len(v.strip()) >= 3:
                                all_samples.append((v.strip(), is_name))

    if not all_samples:
        return None

    seen = set()
    unique_samples = []
    for s_val, is_name in all_samples:
        if s_val.lower() not in seen:
            seen.add(s_val.lower())
            unique_samples.append((s_val, is_name))

    # Clean question to isolate candidate search phrase
    stop_words = {
        "show", "me", "list", "get", "find", "all", "the", "of", "for", "with", "in",
        "by", "on", "at", "to", "a", "an", "is", "are", "was", "were", "who", "whose",
        "details", "record", "records", "search", "query", "check", "info", "information",
        "patient", "patients", "doctor", "doctors", "customer", "customers", "order", "orders",
        "product", "products", "appointment", "appointments", "please", "can", "you",
        "give", "tell", "view", "see", "display", "named", "called", "name", "about"
    }

    prefix_pattern = r"^(?:show|list|get|find|search\s+for|view|display|details\s+of)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:patients?|doctors?|customers?|products?|records?|details?|info)?\s*(?:of\s+)?(?:patients?|doctors?|customers?|products?|records?|details?|info)?\s*(?:named|called|for|with)?\s*"
    candidate_phrase = re.sub(prefix_pattern, "", nl_question.strip(), flags=re.IGNORECASE).strip()
    candidate_phrase = re.sub(r"[^\w\s]", "", candidate_phrase).strip()

    candidate_tokens = [w for w in re.findall(r"\b[a-zA-Z0-9_]+\b", nl_question) if w.lower() not in stop_words and len(w) >= 3]

    # Check for exact matches first: if exact match exists anywhere in question or candidate phrase, no confirmation needed
    q_norm = " " + re.sub(r"[^\w\s]", " ", nl_question.lower()) + " "
    q_norm = re.sub(r"\s+", " ", q_norm)
    for s_val, _ in unique_samples:
        s_clean = " " + re.sub(r"[^\w\s]", " ", s_val.lower()) + " "
        s_clean = re.sub(r"\s+", " ", s_clean)
        if s_clean in q_norm:
            return None

        s_clean_val = re.sub(r"[^\w\s]", "", s_val.lower()).strip()
        if candidate_phrase.lower() == s_clean_val:
            return None
        if set(candidate_phrase.lower().split()) == set(s_clean_val.split()):
            return None
        if s_clean_val and s_clean_val in candidate_phrase.lower():
            return None

    # Determine priority search terms to test
    search_terms = []
    if candidate_phrase and len(candidate_phrase) >= 3 and candidate_phrase.lower() not in stop_words:
        search_terms.append(candidate_phrase)
    for t in candidate_tokens:
        if t not in search_terms:
            search_terms.append(t)

    for term in search_terms:
        term_lower = term.lower()
        best_match = None
        best_score = 0.0

        for s_val, is_name in unique_samples:
            s_lower = s_val.lower()
            s_words = [w.lower() for w in s_val.split()]

            # 1. Exact single-word match in a multi-word sample (e.g. 'harini' matches 'Harini' in 'Harini Krishnan')
            if term_lower in s_words and len(s_words) > 1:
                return (term, s_val)

            # 2. Substring match for names (e.g. 'harini' in 'Harini Krishnan')
            if len(term_lower) >= 4 and term_lower in s_lower:
                return (term, s_val)

            # 3. Fuzzy similarity against individual words in the sample value
            for w in s_words:
                sim = difflib.SequenceMatcher(None, term_lower, w).ratio()
                if sim >= 0.75 and sim > best_score:
                    best_score = sim
                    best_match = s_val

            # 4. Fuzzy similarity against full sample value
            full_sim = difflib.SequenceMatcher(None, term_lower, s_lower).ratio()
            if full_sim >= 0.75 and full_sim > best_score:
                best_score = full_sim
                best_match = s_val

        if best_match and best_score >= 0.75:
            return (term, best_match)

    return None


def generate_sql(
    session_id: str,
    nl_question: str,
    language: str = "auto",
    conversation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate SQL from natural language question using Gemini with clarification, follow-ups, and model fallback.

    Returns:
        dict: {
            "needs_clarification": bool,
            "clarification_question": Optional[str],
            "needs_confirmation": bool,
            "confirmation_question": Optional[str],
            "suggested_value": Optional[str],
            "query_type": str,  # 'select' or 'write'
            "sql": Optional[str],
            "explanation": Optional[str],
            "confidence": float
        }
    """
    global _WORKING_MODEL

    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found. Please connect to a database first.")

    # ---------------------------------------------------------------------------
    # Conversational follow-up: check if preceding message needed confirmation
    # ---------------------------------------------------------------------------
    confirmed_value = None
    if conversation_context and conversation_context.get("previous_confirmation"):
        prev_conf = conversation_context["previous_confirmation"]
        suggested_val = prev_conf.get("suggested_value")
        norm_reply = re.sub(r"[^\w\s]", "", nl_question.strip().lower())

        affirmative_terms = {
            "yes", "yeah", "yep", "yup", "correct", "sure", "ok", "okay",
            "please", "yes please", "confirm", "right", "exactly",
            "aama", "aamam", "seri", "haan", "ha"
        }
        negative_terms = {
            "no", "nope", "nah", "cancel", "dont", "don't", "nevermind", "illai", "illa"
        }

        if norm_reply in affirmative_terms or norm_reply.startswith("yes ") or norm_reply.startswith("yeah "):
            logger.info("User confirmed suggestion '%s' with '%s'", suggested_val, nl_question)
            confirmed_value = suggested_val
            tbl = find_table_for_value(suggested_val, session.get("sample_values"), session.get("schema"))
            if tbl and tbl.lower().startswith("doc"):
                entity_noun = "doctor"
            elif tbl and tbl.lower().startswith("pat"):
                entity_noun = "patient"
            elif tbl and tbl.lower().startswith("prod"):
                entity_noun = "product"
            elif tbl and tbl.lower().startswith("cust"):
                entity_noun = "customer"
            elif tbl:
                entity_noun = tbl.rstrip("s")
            else:
                entity_noun = "record"

            nl_question = f"show details of {entity_noun} {suggested_val}"
            conversation_context = copy.deepcopy(conversation_context)
            conversation_context.pop("previous_confirmation", None)
        elif norm_reply in negative_terms or norm_reply.startswith("no "):
            logger.info("User declined suggestion '%s' with '%s'", suggested_val, nl_question)
            return {
                "needs_confirmation": False,
                "confirmation_question": None,
                "suggested_value": None,
                "data_available": True,
                "unavailable_message": None,
                "corrected_terms": [],
                "needs_clarification": False,
                "clarification_question": None,
                "interpreted_text": nl_question,
                "query_type": "select",
                "sql": None,
                "result": [],
                "explanation": "Understood. Please let me know what you would like to search for instead.",
                "confidence": 1.0,
                "detected_language": detect_input_language(nl_question),
            }
        else:
            logger.info("User provided fresh query '%s' instead of confirming '%s'", nl_question, suggested_val)
            conversation_context = copy.deepcopy(conversation_context)
            conversation_context.pop("previous_confirmation", None)

    # ---------------------------------------------------------------------------
    # Conversational follow-up: check if preceding message needed clarification
    # ---------------------------------------------------------------------------
    if conversation_context:
        prev_type = conversation_context.get("previous_query_type")
        prev_clarif = conversation_context.get("previous_clarification")
        prev_exp = conversation_context.get("previous_explanation") or ""

        # Check if the preceding message asked to clarify between doctor and patient
        is_clarif_followup = (
            prev_type == "clarification"
            or (prev_clarif and prev_clarif.get("needs_clarification"))
            or ("doctor" in prev_exp.lower() and "patient" in prev_exp.lower() and "which one" in prev_exp.lower())
        )
        if is_clarif_followup:
            norm_reply = re.sub(r"[^\w\s]", "", nl_question.strip().lower())
            wants_patient = bool(re.search(r"\b(?:patient|patients|நோயாளி|நோயாளிங்க)\b", norm_reply))
            wants_doctor = bool(re.search(r"\b(?:doctor|doctors|dr|dr\.|மருத்துவர்)\b", norm_reply))

            # Retrieve candidate names
            doc_name = "Dr. James Wilson"
            pat_name = "James Wilson"
            if prev_clarif and prev_clarif.get("matching_tables"):
                doc_name = prev_clarif["matching_tables"].get("doctors", doc_name)
                pat_name = prev_clarif["matching_tables"].get("patients", pat_name)
            else:
                quoted = re.findall(r"'([^']+)'", prev_exp)
                for qn in quoted:
                    if "dr" in qn.lower():
                        doc_name = qn
                    else:
                        pat_name = qn

            if wants_patient and not wants_doctor:
                logger.info("User clarified preference for PATIENT: '%s'", pat_name)
                sql = f"SELECT * FROM patients WHERE LOWER(name) = '{pat_name.lower()}';"
                return {
                    "data_available": True,
                    "unavailable_message": None,
                    "corrected_terms": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "interpreted_text": f"show details of patient {pat_name}",
                    "query_type": "select",
                    "sql": sql,
                    "result": [],
                    "explanation": f"Retrieves all details for patient {pat_name} from the patients table.",
                    "confidence": 0.95,
                    "detected_language": detect_input_language(nl_question),
                    "relevant_tables": ["patients"],
                }
            elif wants_doctor and not wants_patient:
                logger.info("User clarified preference for DOCTOR: '%s'", doc_name)
                core_doc = get_core_person_name(doc_name)
                sql = f"SELECT * FROM doctors WHERE LOWER(name) LIKE '%{core_doc}%';"
                return {
                    "data_available": True,
                    "unavailable_message": None,
                    "corrected_terms": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "interpreted_text": f"show details of doctor {doc_name}",
                    "query_type": "select",
                    "sql": sql,
                    "result": [],
                    "explanation": f"Retrieves all details for doctor {doc_name} from the doctors table.",
                    "confidence": 0.95,
                    "detected_language": detect_input_language(nl_question),
                    "relevant_tables": ["doctors"],
                }


    # ---------------------------------------------------------------------------
    # Response Caching: key = SHA256(schema_sig + normalized_question + language + context)
    # ---------------------------------------------------------------------------
    schema_sig = _compute_schema_signature(session)
    context_sig = (
        f"{conversation_context.get('previous_question', '')}::{conversation_context.get('previous_sql', '')}"
        if conversation_context
        else ""
    )
    cache_key = _generate_cache_key(schema_sig, nl_question, language, context_sig)

    cached_resp = _get_from_cache(cache_key)
    if cached_resp is not None:
        logger.info(
            "[Cache HIT] Skipping Gemini API call; reusing cached response for query: '%s' (key: %s)",
            nl_question,
            cache_key[:12],
        )
        return cached_resp

    schema = session.get("schema", {})
    sample_values_map = session.get("sample_values")

    # Check for near-miss value searches (did-you-mean confirmation flow)
    near_miss = None if confirmed_value else find_near_miss_value(nl_question, schema, sample_values_map)
    if near_miss:
        lit_val, close_val = near_miss
        conf_q = f"I couldn't find an exact match for '{lit_val}'. Did you mean '{close_val}'? Reply yes to see that record, or provide a different name."
        data = {
            "needs_confirmation": True,
            "confirmation_question": conf_q,
            "suggested_value": close_val,
            "literal_value": lit_val,
            "data_available": True,
            "unavailable_message": None,
            "corrected_terms": [],
            "needs_clarification": False,
            "clarification_question": None,
            "interpreted_text": nl_question,
            "query_type": "select",
            "sql": None,
            "result": [],
            "explanation": None,
            "confidence": 0.85,
            "detected_language": detect_input_language(nl_question),
        }
        _put_in_cache(cache_key, data)
        return data

    # Check for multi-table ambiguity (e.g. James Wilson in both doctors and patients)
    multi_table_ambig = detect_multi_table_ambiguity(nl_question, schema, sample_values_map)
    if multi_table_ambig:
        if multi_table_ambig["is_ambiguous"]:
            logger.info("Multi-table ambiguity detected for query: '%s'. Asking for clarification.", nl_question)
            data = {
                "needs_clarification": True,
                "clarification_question": multi_table_ambig["clarification_question"],
                "target_name": multi_table_ambig.get("core_name"),
                "matching_tables": multi_table_ambig.get("matching_tables"),
                "data_available": True,
                "unavailable_message": None,
                "corrected_terms": [],
                "needs_confirmation": False,
                "confirmation_question": None,
                "suggested_value": None,
                "interpreted_text": nl_question,
                "query_type": "select",
                "sql": None,
                "result": [],
                "explanation": None,
                "confidence": 0.3,
                "detected_language": detect_input_language(nl_question),
            }
            _put_in_cache(cache_key, data)
            return data
        else:
            target_table = multi_table_ambig["target_table"]
            target_name = multi_table_ambig["target_name"]
            logger.info("Multi-table entity resolved unambiguously to table '%s' for name '%s'", target_table, target_name)
            q_clean_words = set(re.findall(r"\b[a-zA-Z0-9_]+\b", nl_question.lower()))
            complex_keywords = {"appointment", "appointments", "bill", "billing", "room", "prescribe", "visit", "visits", "treated"}
            if not q_clean_words.intersection(complex_keywords):
                if target_table == "patients":
                    sql = f"SELECT * FROM patients WHERE LOWER(name) = '{target_name.lower()}';"
                    exp = f"Retrieves all details for patient {target_name} from the patients table."
                else:
                    core_doc = get_core_person_name(target_name)
                    sql = f"SELECT * FROM doctors WHERE LOWER(name) LIKE '%{core_doc}%';"
                    exp = f"Retrieves all details for doctor {target_name} from the doctors table."
                data = {
                    "data_available": True,
                    "unavailable_message": None,
                    "corrected_terms": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "interpreted_text": nl_question,
                    "query_type": "select",
                    "sql": sql,
                    "result": [],
                    "explanation": exp,
                    "confidence": 0.95,
                    "detected_language": detect_input_language(nl_question),
                    "relevant_tables": [target_table],
                }
                _put_in_cache(cache_key, data)
                return data

    # Schema-aware retrieval (RAG): retrieve top 3-4 most relevant tables (or all if <= 4)
    from app.services.rag_service import retrieve_relevant_tables
    relevant_tables = retrieve_relevant_tables(session_id, nl_question, top_k=4)

    if relevant_tables and len(relevant_tables) < len(schema):
        logger.info(
            "RAG filtered schema for session '%s' from %d tables to %d relevant tables: %s",
            session_id,
            len(schema),
            len(relevant_tables),
            relevant_tables,
        )
        filtered_schema = {tbl: cols for tbl, cols in schema.items() if tbl in relevant_tables}
        filtered_sample_values = (
            {tbl: vals for tbl, vals in (sample_values_map or {}).items() if tbl in relevant_tables}
            if sample_values_map
            else None
        )
    else:
        filtered_schema = schema
        filtered_sample_values = sample_values_map

    schema_str = _format_schema_for_prompt(filtered_schema, filtered_sample_values)

    detected_lang = detect_input_language(nl_question)
    logger.info("Detected query language for '%s': %s", nl_question, detected_lang)

    if detected_lang == "tamil":
        lang_instruction = """The user's question is in: TAMIL SCRIPT. You MUST write the 'explanation' field and 'clarification_question' field (if used) in Tamil script (தமிழ் எழுத்தில்). Do NOT respond in English. This is a strict requirement, not optional."""
    elif detected_lang == "thanglish":
        lang_instruction = """The user's question is in: THANGLISH (Tamil words in Latin script). You MUST write the 'explanation' field in simple, clear English (since generating Thanglish output reliably is not feasible) — but explicitly acknowledge in one short clause that you understood a Thanglish/Tamil question, e.g. start with 'Understood — ' followed by the English explanation."""
    else:
        lang_instruction = """The user's question is in: ENGLISH. Respond in English as normal."""

    self_check_instruction = """Before finalizing your response, verify: does the 'explanation' field match the required language above? If not, rewrite it in the correct language before responding."""

    # Contextual awareness snippet for follow-up queries
    context_instruction = ""
    if conversation_context and conversation_context.get("previous_question"):
        prev_q = conversation_context.get("previous_question", "")
        prev_sql = conversation_context.get("previous_sql", "")
        context_instruction = f"""
5. Conversational Follow-Up Context:
   - Previous question: "{prev_q}"
   - Previous generated SQL: "{prev_sql}"
   - If the current user question is a follow-up or refinement (e.g., "what about last month?", "only for females", "by product"), interpret it in the context of the previous query and build upon or adjust the previous SQL logic.
"""

    base_prompt = f"""You are an expert SQLite SQL engineer and database analyst.
Given the following SQLite database schema:
{schema_str}

Instructions:
1. Data Availability Assessment (HIGHEST PRIORITY - Must Check FIRST Before Clarification):
   - You MUST FIRST check whether the requested table, entity, or core concept exists in the database schema above.
   - For example: if the user asks for 'patients', 'doctors', or 'patient records', but the schema only contains ecommerce tables ('customers', 'orders', 'products') — patient data DOES NOT EXIST in this database.
   - If the requested data/entity is NOT tracked in the schema:
     - Set "data_available": false
     - Set "unavailable_message": a clear, polite explanation (e.g. "This database tracks ecommerce orders, customers, and products, and does not contain patient data.").
     - Set "sql": null
     - Set "explanation": null
     - Set "needs_clarification": false
     - Set "confidence": 0.85
     - CRITICAL: Do NOT set "needs_clarification": true when the requested entity is absent from the database! Even if the user says 'top patients' or 'best doctors', if the entity does not exist in the schema, it is DATA UNAVAILABLE ("data_available": false), NOT a clarification question.

2. Speech-to-Text Correction & Interpreted Text:
   - The user's input may come from speech recognition, which occasionally mishears words (for example: "shom me pashents older then fourty").
   - Always return an "interpreted_text" field in the JSON response with the corrected sentence.
   - If you corrected any misspelled or phonetically misheard words between the user's input and "interpreted_text", provide them in "corrected_terms" as a list of {{"original": "misheard_word", "corrected": "fixed_word"}}.
   - CRITICAL RULES FOR DATA VALUES AND corrected_terms (STRICT ACCURACY AND DATA INTEGRITY RULES):
     a. LITERAL DATA VALUES (STRICT INTEGRITY RULE): When a user's question includes what looks like a search value for a specific record (a name, an ID, a specific term being filtered on — as opposed to a schema/table/column term), the generated SQL's WHERE clause MUST use the LITERAL text the user typed (case-insensitive match is fine, e.g. LOWER(name) LIKE LOWER('%virthi%')), NEVER a different value, even if a similar-looking value exists in the sample data shown in the prompt.
     b. NO DATA VALUE SUBSTITUTION IN corrected_terms: corrected_terms must NEVER apply to a search/filter value that would change WHICH record is being looked up. It may still correct genuine SCHEMA vocabulary typos (e.g. "paiens" -> "patients", "fourty" -> "forty"), but must NEVER silently swap "virthi" for "Karthik" or any other existing person's name or data value.
     c. EXPLICIT CALIBRATION EXAMPLE (virthi vs Karthik): If the user searches for 'virthi' and no patient named 'virthi' exists, but a patient named 'Karthik' does exist in the database or sample values, do NOT substitute 'Karthik' for 'virthi'. Generate SQL that searches for the literal term 'virthi' (e.g. WHERE LOWER(name) LIKE '%virthi%'), and if it returns zero rows, that is the CORRECT outcome — say 'No patient found with the name \'virthi\'. Please check the spelling and try again.' rather than silently returning Karthik's data.
     d. ZERO-ROWS REASONING ON SEARCH VALUES: When such a query returns zero rows, return a clear explanation like "No patient found with the name 'virthi'. Please check the spelling and try again." — using the ACTUAL term the user typed, not a substituted one.
     e. EXACT CALIBRATION EXAMPLE (Pavai): "Pavai" in "delete the age of patient Pavai" is a person's name (a data value), NOT a misspelling of "patients" — do NOT flag it in corrected_terms, keep "Pavai" intact in interpreted_text, and reference the literal value 'Pavai' in a WHERE clause.
     f. VALID SCHEMA CORRECTIONS: corrected_terms must ONLY correct words that closely match actual schema terms (table names, column names from the connected database, or common query vocabulary like "top", "average", "delete"). Example valid schema correction: [{{"original": "paiens", "corrected": "patients"}}, {{"original": "fourty", "corrected": "forty"}}]
   - If no schema words were corrected, return [].
   - Base your SQL generation on this corrected "interpreted_text".
   - Role & Table Disambiguation for Shared Names: When a person's name exists in multiple tables (e.g. 'James Wilson' in patients vs 'Dr. James Wilson' in doctors):
     - If the user specifies 'patient' (e.g. 'show details of patient James Wilson' or 'patient Dr. James Wilson'), you MUST query the 'patients' table: SELECT * FROM patients WHERE LOWER(name) = 'james wilson';
     - If the user specifies 'doctor' or 'dr' without 'patient' (e.g. 'show details of doctor James Wilson' or 'Dr. James Wilson'), you MUST query the 'doctors' table: SELECT * FROM doctors WHERE LOWER(name) LIKE '%james wilson%';
     - If the user does not specify whether they want the doctor or the patient (e.g. 'show details of James Wilson'), or if both are mentioned ambiguously, set "needs_clarification": true, "clarification_question": "There is a doctor named 'Dr. James Wilson' and a patient named 'James Wilson'. Which one would you like details for (doctor/patient)?", "sql": null, "confidence": 0.3.

3. Clarification & Ambiguity Assessment (ONLY IF data IS available in the schema):
   - Only evaluate this if the requested entity actually exists in the schema.
   - Set "needs_clarification" to true when:
     - A ranking word is used ("top", "best", "highest", "most", "lowest", "yaaru top", "சிறந்த", etc.) on an existing table without specifying BOTH a metric to rank by AND a number/limit (for example: "give me the top patients" or "top patients" on hospital schema is ambiguous, whereas "top 5 patients by number of appointments" specifies both metric and limit and is NOT ambiguous).
     - A vague qualitative term is used with no defined criteria ("important", "recent", "significant", "good", "bad", "mukkiyamaana") without a clear threshold or timeframe.
     - The question could reasonably map to more than one table or column and the correct one cannot be inferred from the schema.
   - Otherwise, if the question has clear criteria or explicit filtering (for example: "list all patients older than 40"), set "needs_clarification" to false.

4. Language & Dialect Understanding (English, Tamil, and Thanglish):
   - Understand the intent accurately whether the user writes in English, Tamil script, or Thanglish (Tamil words written in Latin/English script).
   - Thanglish calibrations:
     - "40 vayasuku mela patients kaatu" means "show/list patients older than 40".
     - "doctor ellam list pannu" means "list all doctors".
{context_instruction}
6. Multi-Statement Queries & Controlled Write Operations:
   - Schema-destructive DDL operations (DROP TABLE, DROP DATABASE, ALTER TABLE, TRUNCATE, CREATE) are STRICTLY FORBIDDEN and dangerous. If the user asks to drop, delete tables, or alter schema, DO NOT generate a DROP or DDL statement. Set "sql": null, set "explanation": "Dropping tables or modifying database schema is strictly prohibited.", set "query_type": "select", "confidence": 0.0.
   - Multiple queries separated by semicolons (;) are fully supported.
   - If the user asks to insert, update, or delete data AND also asks to return, show, list, or view data (e.g. "Add patient X ... and return the full patients table", "Insert new appointment ... and show appointments"):
     - You MUST generate BOTH statements in sequence separated by a semicolon (;).
     - Example: INSERT INTO patients (name, age, gender, diagnosis, admission_date) VALUES ('Prem', 8, 'Male', 'Headache', '2026-04-23'); SELECT * FROM patients;
     - Set "query_type": "write".
     - In "explanation", explicitly mention both operations (adding the record and retrieving the table).
   - If the user asks to "delete / remove / clear the <column> of <entity>" (e.g. "delete the age of the patient pavai", "remove diagnosis of patient 3", "clear city of customer John"):
     - This is an attribute clearing operation, NOT a row or table deletion!
     - You MUST generate an UPDATE query setting that specific column to NULL:
       e.g. UPDATE patients SET age = NULL WHERE LOWER(name) = 'pavai';
     - Do NOT generate a DELETE query unless the user specifically asks to delete the record/patient/row itself.
     - ALWAYS use case-insensitive matching (e.g. LOWER(name) = 'pavai' or name LIKE 'Pavai') to ensure the row matches regardless of casing.
     - Set "query_type": "write".
   - If the user only asks to modify data (without asking to return/view data):
     - Generate the appropriate INSERT, UPDATE, or DELETE query.
     - For UPDATE and DELETE: You MUST ALWAYS include a precise WHERE clause targeting only the requested rows.
     - Set "query_type": "write".
   - If the user asks multiple read queries (e.g. "Count of patients and count of doctors"):
     - You can generate multiple SELECT statements separated by a semicolon: e.g. SELECT COUNT(*) AS total_patients FROM patients; SELECT COUNT(*) AS total_doctors FROM doctors;
     - Set "query_type": "select".
   - For all read-only queries, set "query_type": "select".

7. Entity Conjunctions (AND / OR) vs Attribute Filters:
   - When a user asks for multiple distinct entities (e.g. "patient 1 and patient 2", "details of Alice Jenkins and Bob", "patient A & patient B", "patient A as well as patient B", "A, B and C", "patient 1 or patient 2"):
     The user is requesting records for EACH independent entity.
     CRITICAL: In SQL, a single database row CANNOT satisfy two different equality conditions on the same column at once.
     NEVER generate a mutually exclusive condition like: WHERE name = 'Patient 1' AND name = 'Patient 2' (this returns 0 rows!).
     ALWAYS generate: WHERE LOWER(name) IN ('patient 1', 'patient 2') OR WHERE (LOWER(name) = 'patient 1' OR LOWER(name) = 'patient 2').
     If entities might be numeric IDs or names (e.g. 'patient 1 and patient 2'), support both: WHERE id IN (1, 2) OR LOWER(name) IN ('patient 1', 'patient 2').
   - When user specifies OR for entities ("patient 1 or patient 2"):
     Generate: WHERE LOWER(name) IN ('patient 1', 'patient 2') OR id IN (1, 2).
   - Attribute / Filter conjunctions ("diabetic patients older than 60", "age > 50 and gender = female", "diabetic or hypertensive"):
     MUST preserve standard boolean logic: WHERE diagnosis = 'diabetes' AND age > 60.
     Do NOT confuse entity conjunctions with attribute filtering.

8. Output Structure Rules:
   - If "data_available" is false:
     - "data_available": false
     - "unavailable_message": a calm informational message
     - "corrected_terms": [...]
     - "needs_clarification": false
     - "clarification_question": null
     - "interpreted_text": the corrected/cleaned input question
     - "query_type": "select"
     - "sql": null
     - "explanation": null
     - "confidence": 0.85
   - Else if "needs_clarification" is true:
     - "data_available": true
     - "unavailable_message": null
     - "corrected_terms": [...]
     - "needs_clarification": true
     - "clarification_question": a short, specific, polite question asking the user to clarify the ambiguity.
     - "interpreted_text": the corrected/cleaned version of the input question.
     - "query_type": "select"
     - "sql": null
     - "explanation": null
     - "confidence": a float below 0.5 (e.g. 0.2 or 0.3)
   - Else:
     - "data_available": true
     - "unavailable_message": null
     - "corrected_terms": [...]
     - "needs_clarification": false
     - "clarification_question": null
     - "interpreted_text": the corrected/cleaned version of the input question.
     - "query_type": "write" if any statement performs an insert/update/delete, otherwise "select"
     - "sql": valid, executable SQLite query statement(s) (use semicolons if multiple statements were requested) that accurately answer the question based on the interpreted text.
     - "explanation": a concise explanation of how the query operates.
     - "confidence": a float between 0.7 and 1.0.

User Question to Answer:
"{nl_question}"

Language Instruction:
{lang_instruction}

Self-Check:
{self_check_instruction}

CRITICAL: Return ONLY a single valid JSON object. Do not include markdown code fences (```json or ```), backticks, or any introductory or concluding text.
Format:
{{
  "data_available": true,
  "unavailable_message": null,
  "corrected_terms": [],
  "needs_clarification": false,
  "clarification_question": null,
  "interpreted_text": "the corrected/cleaned version of the input",
  "query_type": "select",
  "sql": "SELECT ...",
  "explanation": "...",
  "confidence": 0.95
}}
"""

    gen_config = {
        "temperature": 0.0,
        "max_output_tokens": 800,
    }

    last_error = None

    # Always prioritize the currently confirmed working model first
    models_to_try = [_WORKING_MODEL] + [m for m in MODELS_TO_TRY if m != _WORKING_MODEL]

    for model_name in models_to_try:
        try:
            logger.info("Attempting SQL generation with model: %s", model_name)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                base_prompt,
                generation_config=gen_config,
                request_options={"timeout": 30.0},
            )
            raw_text = response.text or ""
            cleaned = _clean_json_string(raw_text)

            try:
                data = json.loads(cleaned)
                if data.get("sql"):
                    data["sql"] = fix_mutually_exclusive_and(data["sql"])
                _validate_result(data, nl_question, filtered_schema, filtered_sample_values)
                _enforce_language(data, detected_lang, model)
                data["relevant_tables"] = relevant_tables
                _WORKING_MODEL = model_name
                _put_in_cache(cache_key, data)
                return data
            except Exception as parse_err:
                logger.warning(
                    "JSON parse error with model %s (%s). Retrying once with strict instructions...",
                    model_name,
                    parse_err,
                )
                retry_prompt = f"""Your previous response was not valid JSON.
Error: {str(parse_err)}
Database Schema:
{schema_str}

Instructions:
1. FIRST check if the requested entity/data exists in the schema. If absent, set "data_available": false, provide "unavailable_message", set sql to null, needs_clarification: false. Do not ask for clarification if data does not exist in schema.
2. Determine if the question needs clarification (ONLY IF data exists in schema: e.g. ranking word without metric and limit on existing tables).
3. Fix speech-to-text mistakes in interpreted_text and list {{"original", "corrected"}} pairs in corrected_terms ONLY for schema keywords or SQL terms. NEVER substitute person names or data values (e.g. searching 'virthi' must use literal 'virthi' in WHERE clause, never 'Karthik').
4. If needs_clarification is true, set sql to null, explanation to null, confidence < 0.5, and provide a short clarification_question.
5. If valid and available, generate valid SQLite in sql, explanation, confidence >= 0.5.

User Question to Answer:
"{nl_question}"

Language Instruction:
{lang_instruction}

Self-Check:
{self_check_instruction}

Output ONLY raw valid JSON without markdown formatting or backticks:
{{
  "data_available": true or false,
  "unavailable_message": "..." or null,
  "corrected_terms": [],
  "needs_clarification": true or false,
  "clarification_question": "..." or null,
  "interpreted_text": "corrected sentence",
  "sql": "..." or null,
  "explanation": "..." or null,
  "confidence": 0.3 or 0.9
}}
"""
                retry_res = model.generate_content(retry_prompt, generation_config=gen_config)
                retry_cleaned = _clean_json_string(retry_res.text or "")
                retry_data = json.loads(retry_cleaned)
                if retry_data.get("sql"):
                    retry_data["sql"] = fix_mutually_exclusive_and(retry_data["sql"])
                _validate_result(retry_data, nl_question, filtered_schema, filtered_sample_values)
                _enforce_language(retry_data, detected_lang, model)
                retry_data["relevant_tables"] = relevant_tables
                _WORKING_MODEL = model_name
                _put_in_cache(cache_key, retry_data)
                return retry_data

        except Exception as exc:
            logger.warning(
                "Model '%s' failed (error: %s: %s). Trying next fallback model...",
                model_name,
                type(exc).__name__,
                exc,
            )
            last_error = exc
            continue

    logger.warning("All Gemini model generation attempts failed with error: %s. Using graceful fallback.", last_error)

    # Check if this was a multi-entity query for fallback SQL generation
    conjunction = extract_entity_conjunctions(nl_question)
    if conjunction and filtered_schema:
        target_table = "patients" if conjunction.get("entity_type") == "patient" else "doctors" if conjunction.get("entity_type") == "doctor" else list(filtered_schema.keys())[0]
        if target_table in filtered_schema:
            ids = []
            names = []
            for ent in conjunction.get("entities", []):
                id_m = re.search(r"\b(\d+)\b", ent)
                if id_m:
                    ids.append(int(id_m.group(1)))
                clean_name = re.sub(r"^(?:patient|doctor)\s+", "", ent, flags=re.IGNORECASE).strip()
                if clean_name:
                    names.append(clean_name.replace("'", "''"))

            where_clauses = []
            if ids:
                where_clauses.append(f"id IN ({', '.join(str(i) for i in ids)})")
            if names:
                name_in = ", ".join(f"'{n.lower()}'" for n in names)
                where_clauses.append(f"LOWER(name) IN ({name_in})")

            where_expr = " OR ".join(where_clauses) if where_clauses else "1=1"
            fallback_sql = f"SELECT * FROM {target_table} WHERE {where_expr};"
            return {
                "data_available": True,
                "unavailable_message": None,
                "corrected_terms": [],
                "needs_clarification": False,
                "clarification_question": None,
                "interpreted_text": nl_question,
                "query_type": "select",
                "sql": fallback_sql,
                "explanation": f"Retrieves records matching {', '.join(conjunction.get('entities', []))} from {target_table}.",
                "confidence": 0.9,
                "detected_language": detected_lang,
                "relevant_tables": [target_table],
            }

    return {
        "data_available": True,
        "unavailable_message": None,
        "corrected_terms": _extract_word_corrections(nl_question, nl_question),
        "needs_clarification": True,
        "clarification_question": "I could not generate a SQL query for this question right now. Could you please clarify your request with more specific criteria or table names?",
        "needs_confirmation": False,
        "confirmation_question": None,
        "suggested_value": None,
        "interpreted_text": nl_question,
        "sql": None,
        "explanation": None,
        "confidence": 0.2,
        "detected_language": detected_lang,
        "relevant_tables": relevant_tables,
    }



def _extract_word_corrections(original: str, corrected: str) -> list:
    """Extract individual {original, corrected} word pairs between input and interpreted text."""
    if not original or not corrected:
        return []
    orig_words = re.findall(r"\w+|[^\w\s]", original)
    corr_words = re.findall(r"\w+|[^\w\s]", corrected)
    matcher = difflib.SequenceMatcher(None, [w.lower() for w in orig_words], [w.lower() for w in corr_words])
    pairs = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            orig_chunk = " ".join(orig_words[i1:i2]).strip()
            corr_chunk = " ".join(corr_words[j1:j2]).strip()
            if orig_chunk.lower() != corr_chunk.lower():
                pairs.append({"original": orig_chunk, "corrected": corr_chunk})
    return pairs


def _validate_result(
    data: Any,
    nl_question: str = "",
    schema: Optional[Dict[str, Any]] = None,
    sample_values: Optional[Dict[str, Any]] = None,
) -> None:
    """Ensure result dictionary contains required fields with expected types and enforces data value integrity."""
    if not isinstance(data, dict):
        return

    # Normalize interpreted_text
    interpreted = data.get("interpreted_text")
    if not interpreted or not isinstance(interpreted, str) or not interpreted.strip():
        data["interpreted_text"] = nl_question
    else:
        data["interpreted_text"] = interpreted.strip()

    # Collect known schema terms (tables, columns, and standard SQL vocabulary)
    schema_terms = set()
    all_sample_values = set()
    if schema:
        for tbl, cols in schema.items():
            schema_terms.add(tbl.lower())
            if tbl.lower().endswith("s"):
                schema_terms.add(tbl.lower()[:-1])
            if isinstance(cols, list):
                for c in cols:
                    if isinstance(c, dict):
                        schema_terms.add(c.get("name", "").lower())
                        for sv in c.get("sample_values") or []:
                            if sv is not None:
                                sv_str = str(sv).strip().lower()
                                if sv_str:
                                    all_sample_values.add(sv_str)
                                    for word in sv_str.split():
                                        if len(word) >= 3:
                                            all_sample_values.add(word)
                    else:
                        schema_terms.add(str(c).lower())

    if sample_values:
        for tbl, cols_dict in sample_values.items():
            if isinstance(cols_dict, dict):
                for col_name, s_list in cols_dict.items():
                    if isinstance(s_list, list):
                        for sv in s_list:
                            if sv is not None:
                                sv_str = str(sv).strip().lower()
                                if sv_str:
                                    all_sample_values.add(sv_str)
                                    for word in sv_str.split():
                                        if len(word) >= 3:
                                            all_sample_values.add(word)

    # Common valid schema / query vocabulary terms that are permitted in corrected_terms
    common_vocab = {
        "top", "best", "average", "avg", "count", "sum", "min", "max",
        "delete", "remove", "clear", "update", "insert", "add", "show",
        "list", "get", "find", "display", "select", "where", "order",
        "group", "by", "having", "join", "inner", "left", "right",
        "older", "younger", "greater", "less", "more", "between",
        "recent", "all", "patient", "patients", "doctor", "doctors",
        "appointment", "appointments", "hospital", "hospitals",
        "customer", "customers", "order", "orders", "product", "products",
        "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred"
    }
    schema_terms.update(common_vocab)

    def _is_schema_term(term: str) -> bool:
        t = term.lower()
        if t in schema_terms:
            return True
        matches = difflib.get_close_matches(t, list(schema_terms), n=1, cutoff=0.85)
        return len(matches) > 0

    def _is_data_value(term: str) -> bool:
        t = term.lower()
        if t in all_sample_values:
            return True
        for sv in all_sample_values:
            if t == sv or (len(t) >= 4 and t in sv) or (len(sv) >= 4 and sv in t):
                return True
            if difflib.SequenceMatcher(None, t, sv).ratio() >= 0.75:
                return True
        return False

    # Check if the query references a core entity completely absent from schema
    data_available = bool(data.get("data_available", True))
    if schema:
        q_tokens = set(re.findall(r"\b[a-zA-Z]+\b", nl_question.lower()))
        schema_tokens = set()
        for tbl, cols in schema.items():
            schema_tokens.add(tbl.lower())
            for c in cols:
                c_name = c.get("name", "") if isinstance(c, dict) else str(c)
                schema_tokens.add(c_name.lower())

        foreign_entity_keywords = [
            "patient", "patients", "doctor", "doctors", "appointment", "appointments", "hospital",
            "customer", "customers", "order", "orders", "product", "products", "sales", "revenue",
            "student", "students", "course", "courses", "teacher", "teachers", "weather", "stocks"
        ]
        for ek in foreign_entity_keywords:
            if ek in q_tokens and not any(ek in st for st in schema_tokens):
                data_available = False
                data["data_available"] = False
                data["unavailable_message"] = f"This database does not contain information about {ek}."
                data["sql"] = None
                data["explanation"] = None
                data["needs_clarification"] = False
                data["clarification_question"] = None
                break

    data["data_available"] = data_available
    if not data_available:
        unavail_msg = data.get("unavailable_message")
        if not unavail_msg or not isinstance(unavail_msg, str) or not unavail_msg.strip():
            data["unavailable_message"] = "This information is not tracked in the connected database schema."
        else:
            data["unavailable_message"] = unavail_msg.strip()
        data["sql"] = None
        data["explanation"] = None
        data["needs_clarification"] = False
        data["clarification_question"] = None
        try:
            conf = float(data.get("confidence", 0.85))
            data["confidence"] = conf
        except (ValueError, TypeError):
            data["confidence"] = 0.85
    else:
        data["unavailable_message"] = None

    # Normalize corrected_terms & apply Bug 2 Safety Net:
    # If corrected_terms contains an entry where "corrected" does not match schema vocabulary
    # but matches a data value in sample_values, reject that correction (drop from corrected_terms,
    # and revert from interpreted_text and SQL).
    corrected_terms = data.get("corrected_terms")
    valid_pairs = []
    rejected_data_corrections = []
    sql_text = str(data.get("sql") or "").lower()

    if isinstance(corrected_terms, list):
        for item in corrected_terms:
            if isinstance(item, dict) and "original" in item and "corrected" in item:
                orig = str(item["original"]).strip()
                corr = str(item["corrected"]).strip()
                if orig and corr and orig.lower() != corr.lower():
                    # Check safety net: is corrected value a data value rather than schema term?
                    if not _is_schema_term(corr) and _is_data_value(corr):
                        logger.warning(
                            "[Safety Net] Rejecting data value auto-correction: '%s' -> '%s' (matches sample data value). Reverting to literal user term.",
                            orig, corr
                        )
                        rejected_data_corrections.append((orig, corr))
                        continue

                    # Safeguard: Do not flag names or data values that appear as literal values in the generated SQL
                    orig_l = orig.lower()
                    if f"'{orig_l}'" in sql_text or f'"{orig_l}"' in sql_text or f"%{orig_l}%" in sql_text:
                        continue
                    valid_pairs.append({"original": orig, "corrected": corr})

    # If model did not output pairs but input was corrected, derive automatically and filter
    if not valid_pairs and data.get("interpreted_text") and nl_question:
        extracted = _extract_word_corrections(nl_question, data["interpreted_text"])
        for p in extracted:
            orig = p["original"]
            corr = p["corrected"]
            if not _is_schema_term(corr) and _is_data_value(corr):
                logger.warning(
                    "[Safety Net] Rejecting derived data value auto-correction: '%s' -> '%s'. Reverting to literal user term.",
                    orig, corr
                )
                rejected_data_corrections.append((orig, corr))
                continue
            orig_l = orig.lower()
            if f"'{orig_l}'" in sql_text or f'"{orig_l}"' in sql_text or f"%{orig_l}%" in sql_text:
                continue
            valid_pairs.append(p)

    data["corrected_terms"] = valid_pairs

    # Revert rejected data corrections from interpreted_text, sql, and explanation
    for orig, corr in rejected_data_corrections:
        if data.get("interpreted_text"):
            data["interpreted_text"] = re.sub(rf"\b{re.escape(corr)}\b", orig, data["interpreted_text"], flags=re.IGNORECASE)
        if data.get("sql"):
            data["sql"] = re.sub(rf"\b{re.escape(corr)}\b", orig, data["sql"], flags=re.IGNORECASE)
        if data.get("explanation"):
            data["explanation"] = re.sub(rf"\b{re.escape(corr)}\b", orig, data["explanation"], flags=re.IGNORECASE)

    # Additional safety net: Check if SQL WHERE clause contains a sample data value not present in user query
    if data.get("sql") and nl_question:
        sql_str = data["sql"]
        stop_words = {
            "show", "me", "list", "get", "find", "all", "the", "of", "for", "with", "in",
            "by", "on", "at", "to", "a", "an", "is", "are", "was", "were", "who", "whose",
            "details", "record", "records", "search", "query", "check", "info", "information"
        }
        q_non_schema_words = [
            w for w in re.findall(r"\b[a-zA-Z0-9_]+\b", nl_question)
            if w.lower() not in stop_words and not _is_schema_term(w)
        ]
        sql_literals = re.findall(r"['\"]%?([^%'\"]+)%?['\"]", sql_str)
        for lit in sql_literals:
            lit_lower = lit.lower()
            if _is_data_value(lit_lower) and not _is_schema_term(lit_lower):
                if lit_lower not in nl_question.lower():
                    # Sample data value was used in SQL without appearing in user question
                    for qw in q_non_schema_words:
                        if qw.lower() not in sql_str.lower():
                            logger.warning(
                                "[Safety Net] Silent data substitution detected: '%s' in SQL replaced user term '%s'. Reverting SQL to user literal.",
                                lit, qw
                            )
                            data["sql"] = data["sql"].replace(lit, qw)
                            if data.get("interpreted_text"):
                                data["interpreted_text"] = re.sub(rf"\b{re.escape(lit)}\b", qw, data["interpreted_text"], flags=re.IGNORECASE)
                            if data.get("explanation"):
                                data["explanation"] = re.sub(rf"\b{re.escape(lit)}\b", qw, data["explanation"], flags=re.IGNORECASE)
                            break

    if not data_available:
        return

    # Normalize confirmation and clarification fields
    data["needs_confirmation"] = bool(data.get("needs_confirmation", False))
    data["confirmation_question"] = data.get("confirmation_question")
    data["suggested_value"] = data.get("suggested_value")

    if data["needs_confirmation"]:
        data["sql"] = None
        data["explanation"] = None
        data["needs_clarification"] = False
        data["clarification_question"] = None
        return

    # Normalize needs_clarification
    needs_clarif = bool(data.get("needs_clarification", False))
    data["needs_clarification"] = needs_clarif

    if needs_clarif:
        clarif_q = data.get("clarification_question")
        if not clarif_q or not isinstance(clarif_q, str) or not clarif_q.strip():
            data["clarification_question"] = "Could you please clarify your request with more specific criteria?"
        else:
            data["clarification_question"] = clarif_q.strip()
        data["sql"] = None
        data["explanation"] = None
        try:
            conf = float(data.get("confidence", 0.3))
            data["confidence"] = min(conf, 0.49)
        except (ValueError, TypeError):
            data["confidence"] = 0.3
    else:
        data["clarification_question"] = None
        sql = data.get("sql")
        if not sql or not isinstance(sql, str) or not sql.strip():
            explanation = (data.get("explanation") or "").strip()
            data["needs_clarification"] = True
            data["clarification_question"] = explanation or "Could you please clarify your request?"
            data["sql"] = None
            data["confidence"] = 0.3
        else:
            data["sql"] = sql.strip()
            upper_sql = data["sql"].upper()
            if any(upper_sql.startswith(k) for k in ("DROP", "ALTER", "TRUNCATE", "CREATE")):
                data["sql"] = None
                data["explanation"] = "Schema modification operations (such as DROP or ALTER TABLE) are prohibited."
                data["confidence"] = 0.0
                data["query_type"] = "select"
            elif upper_sql.startswith("INSERT") or upper_sql.startswith("UPDATE") or upper_sql.startswith("DELETE"):
                data["query_type"] = "write"
                explanation = data.get("explanation")
                data["explanation"] = explanation.strip() if isinstance(explanation, str) else ""
                try:
                    conf = float(data.get("confidence", 0.9))
                    data["confidence"] = max(conf, 0.5)
                except (ValueError, TypeError):
                    data["confidence"] = 0.9
            else:
                data["query_type"] = data.get("query_type", "select")
                if data["query_type"] not in ("select", "write"):
                    data["query_type"] = "select"
                explanation = data.get("explanation")
                data["explanation"] = explanation.strip() if isinstance(explanation, str) else ""
                try:
                    conf = float(data.get("confidence", 0.9))
                    data["confidence"] = max(conf, 0.5)
                except (ValueError, TypeError):
                    data["confidence"] = 0.9


def regenerate_sql(
    session_id: str,
    original_question: str,
    failed_sql: str,
    error_message: str,
) -> Dict[str, Any]:
    """Regenerate and fix a failed SQL query using Gemini with explicit failure context.

    Sends the original user question, the failed SQL query, and the exact error message
    (from sqlglot AST validation or SQLite execution) back to Gemini for self-correction.
    """
    global _WORKING_MODEL

    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session '{session_id}' not found. Please connect to a database first.")

    schema = session.get("schema", {})
    sample_values_map = session.get("sample_values")

    # Schema-aware retrieval (RAG)
    from app.services.rag_service import retrieve_relevant_tables
    relevant_tables = retrieve_relevant_tables(session_id, original_question, top_k=4)

    if relevant_tables and len(relevant_tables) < len(schema):
        filtered_schema = {tbl: cols for tbl, cols in schema.items() if tbl in relevant_tables}
        filtered_sample_values = (
            {tbl: vals for tbl, vals in (sample_values_map or {}).items() if tbl in relevant_tables}
            if sample_values_map
            else None
        )
    else:
        filtered_schema = schema
        filtered_sample_values = sample_values_map

    schema_str = _format_schema_for_prompt(filtered_schema, filtered_sample_values)
    detected_lang = detect_input_language(original_question)

    if detected_lang == "tamil":
        lang_instruction = """The user's question is in: TAMIL SCRIPT. You MUST write the 'explanation' field in Tamil script (தமிழ் எழுத்தில்). Do NOT respond in English."""
    elif detected_lang == "thanglish":
        lang_instruction = """The user's question is in: THANGLISH. Write the 'explanation' in English starting with 'Understood — '."""
    else:
        lang_instruction = """The user's question is in: ENGLISH. Respond in English as normal."""

    self_check_instruction = """Before finalizing your response, verify: does the corrected SQL fix the exact error specified, and does the 'explanation' match the required language?"""

    prompt = f"""You are an expert SQLite SQL engineer and database analyst.
A previously generated SQL query failed validation or database execution. Your task is to diagnose the error and provide a corrected, working SQLite query.

Original User Question:
"{original_question}"

Failed SQL Query:
{failed_sql}

Exact Error Message:
{error_message}

Database Schema and Sample Values:
{schema_str}

Instructions:
1. Carefully analyze the Error Message and Failed SQL Query:
   - Check if an invalid column or table name was referenced, and replace it with the exact column/table name from the schema above.
   - Check if there was a syntax error (e.g. missing commas, misplaced keywords, unclosed quotes, invalid aliases) and fix it.
   - Ensure all joins match valid foreign keys or column types.
2. Produce a corrected, fully valid, executable SQLite query that accurately answers the user's question.
3. Provide a clear, concise explanation of the corrected query.
4. Output ONLY a single raw valid JSON object without markdown fences, code blocks, or backticks:
{{
  "needs_clarification": false,
  "clarification_question": null,
  "interpreted_text": "{original_question}",
  "sql": "SELECT ...",
  "explanation": "...",
  "confidence": 0.95
}}

Language Instruction:
{lang_instruction}

Self-Check:
{self_check_instruction}
"""

    gen_config = {
        "temperature": 0.0,
        "max_output_tokens": 800,
    }

    last_error = None
    models_to_try = [_WORKING_MODEL] + [m for m in MODELS_TO_TRY if m != _WORKING_MODEL]

    for model_name in models_to_try:
        try:
            logger.info("Attempting SQL self-correction with model: %s", model_name)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt, generation_config=gen_config)
            raw_text = response.text or ""
            cleaned = _clean_json_string(raw_text)

            try:
                data = json.loads(cleaned)
                _validate_result(data, original_question, filtered_schema, filtered_sample_values)
                _enforce_language(data, detected_lang, model)
                data["relevant_tables"] = relevant_tables
                _WORKING_MODEL = model_name
                return data
            except Exception as parse_err:
                logger.warning(
                    "JSON parse error during self-correction with model %s (%s). Retrying...",
                    model_name,
                    parse_err,
                )
                retry_prompt = f"""Your previous response was not valid JSON.
Error: {str(parse_err)}
Database Schema:
{schema_str}

Output ONLY raw valid JSON:
{{
  "needs_clarification": false,
  "clarification_question": null,
  "interpreted_text": "{original_question}",
  "sql": "SELECT ...",
  "explanation": "...",
  "confidence": 0.9
}}
"""
                retry_res = model.generate_content(retry_prompt, generation_config=gen_config)
                retry_cleaned = _clean_json_string(retry_res.text or "")
                retry_data = json.loads(retry_cleaned)
                _validate_result(retry_data, original_question, filtered_schema, filtered_sample_values)
                _enforce_language(retry_data, detected_lang, model)
                retry_data["relevant_tables"] = relevant_tables
                _WORKING_MODEL = model_name
                return retry_data

        except Exception as exc:
            logger.warning(
                "Self-correction model '%s' failed (error: %s: %s). Trying next fallback model...",
                model_name,
                type(exc).__name__,
                exc,
            )
            last_error = exc
            continue

    if last_error:
        raise last_error
    raise RuntimeError("All Gemini model self-correction attempts failed.")


def generate_zero_result_explanation(
    question: str,
    sql: str,
    original_explanation: Optional[str] = None,
    detected_language: str = "english",
) -> str:
    """Generate a clear, friendly explanation when a SELECT query executes successfully but returns 0 rows.

    Restates the actual condition or search value that was checked:
    - Specific name/value search: "No patient found with the name 'virthi'. Please check the spelling and try again."
    - Criteria search: "Query executed successfully — no patients found matching 'visited in the last 5 days'."
    """
    # 1. Determine entity
    q_lower = question.lower()
    sql_lower = sql.lower()
    if "patient" in q_lower or "patients" in q_lower or "patients" in sql_lower:
        entity = "patient"
        entity_plural = "patients"
    elif "doctor" in q_lower or "doctors" in q_lower or "doctors" in sql_lower:
        entity = "doctor"
        entity_plural = "doctors"
    elif "customer" in q_lower or "customers" in q_lower or "customers" in sql_lower:
        entity = "customer"
        entity_plural = "customers"
    elif "product" in q_lower or "products" in q_lower or "products" in sql_lower:
        entity = "product"
        entity_plural = "products"
    elif "order" in q_lower or "orders" in q_lower or "orders" in sql_lower:
        entity = "order"
        entity_plural = "orders"
    elif "appointment" in q_lower or "appointments" in q_lower or "appointments" in sql_lower:
        entity = "appointment"
        entity_plural = "appointments"
    else:
        entity = "record"
        entity_plural = "records"

    # 2. Check if a specific name or literal search term was queried in SQL WHERE clause
    # e.g. WHERE LOWER(name) LIKE '%virthi%' or WHERE name = 'xyzabc123'
    name_col_pattern = r"(?:WHERE|AND|OR)\s+(?:LOWER\s*\(\s*)?([a-zA-Z0-9_]+)(?:\s*\))?\s*(?:LIKE|=)\s*['\"]%?([^%'\"]+)%?['\"]"
    name_matches = re.findall(name_col_pattern, sql, re.IGNORECASE)

    specific_search_val = None
    is_name_search = False

    for col_name, val in name_matches:
        val_clean = val.strip()
        col_lower = col_name.lower()
        if col_lower in ("name", "patient_name", "doctor_name", "customer_name", "product_name"):
            specific_search_val = val_clean
            is_name_search = True
            break
        elif any(w.lower() == val_clean.lower() for w in re.findall(r"\b[a-zA-Z0-9_]+\b", question)):
            # Literal value appears directly in user question and is not a common keyword
            if val_clean.lower() not in ("completed", "scheduled", "cancelled", "male", "female", "active"):
                specific_search_val = val_clean
                if "name" in q_lower or entity in ("patient", "doctor", "customer"):
                    is_name_search = True
                break

    # If not found via regex above, check if question contains a specific unquoted search token (e.g. virthi, xyzabc123)
    if not specific_search_val:
        stop_words = {
            "show", "me", "list", "get", "find", "all", "the", "of", "for", "with", "in",
            "by", "on", "at", "to", "a", "an", "is", "are", "was", "were", "who", "whose",
            "details", "record", "records", "search", "query", "check", "info", "information",
            "patients", "patient", "doctors", "doctor", "customers", "customer", "orders", "order",
            "products", "product", "appointments", "appointment", "named", "name", "called"
        }
        tokens = [w for w in re.findall(r"\b[a-zA-Z0-9_]+\b", question) if w.lower() not in stop_words and len(w) > 2]
        for token in tokens:
            if token.lower() in sql_lower:
                specific_search_val = token
                is_name_search = True
                break

    # 3. Rule-based explanation construction
    if specific_search_val:
        if is_name_search:
            explanation = f"No {entity} found with the name '{specific_search_val}'. Please check the spelling and try again."
        else:
            explanation = f"Query executed successfully — no {entity_plural} found matching '{specific_search_val}'."
    else:
        # Criteria search (e.g. "patients visited last 5 days" or "patients older than 90")
        criteria = re.sub(
            r"^(?:list\s+of|show\s+me|find|get|give\s+me|display|search\s+for|what\s+are\s+the|which)\s+",
            "",
            question.strip(),
            flags=re.IGNORECASE,
        ).strip()
        if criteria.lower().startswith(entity_plural):
            remainder = criteria[len(entity_plural):].strip()
            if remainder.startswith("who ") or remainder.startswith("that ") or remainder.startswith("with ") or remainder.startswith("visited") or remainder.startswith("in "):
                explanation = f"Query executed successfully — no {entity_plural} found {remainder}."
            elif remainder:
                explanation = f"Query executed successfully — no {entity_plural} found matching '{remainder}'."
            else:
                explanation = f"Query executed successfully — no {entity_plural} found."
        elif criteria.lower().startswith(entity):
            remainder = criteria[len(entity):].strip()
            if remainder:
                explanation = f"Query executed successfully — no {entity} found matching '{remainder}'."
            else:
                explanation = f"Query executed successfully — no {entity} found."
        else:
            explanation = f"Query executed successfully — no {entity_plural} found matching '{criteria}'."

    # 4. Optional Gemini enhancement if model is available and query is English/complex
    if GEMINI_API_KEY and detected_language not in ("tamil", "thanglish"):
        try:
            model = genai.GenerativeModel(_WORKING_MODEL)
            zero_prompt = f"""You are an assistant reporting SQLite database query results.
A query executed successfully against SQLite but returned 0 rows (no matching records found).

User Question: "{question}"
Executed SQL: "{sql}"
Original Description: "{original_explanation or ''}"

Write a clear, concise, user-friendly 1-sentence explanation stating that the query executed successfully but found no matching records.
STRICT RULES:
1. Restate the specific condition or criteria that was checked (e.g., "Query executed successfully — no patients found matching 'visited in the last 5 days'." or "No patient found with the name 'virthi'. Please check the spelling and try again.").
2. If the user searched for a specific name, ID, or term, you MUST use the EXACT literal term the user typed (e.g., 'virthi', 'xyzabc123'). NEVER substitute it with another name or existing database record.
3. Keep it polite, clear, and reassuring.
4. Output ONLY the plain explanation sentence, without quotes, backticks, or JSON.
"""
            resp = model.generate_content(
                zero_prompt,
                generation_config={"temperature": 0.0, "max_output_tokens": 80},
                request_options={"timeout": 4.0},
            )
            resp_text = (resp.text or "").strip().strip('"').strip("'")
            if resp_text and len(resp_text) > 10 and not resp_text.startswith("{"):
                # Ensure the exact search value was not mangled by Gemini
                if not specific_search_val or specific_search_val.lower() in resp_text.lower():
                    explanation = resp_text
        except Exception as g_err:
            logger.debug("Gemini zero-result explanation call failed or timed out: %s", g_err)

    # 5. Language constraints
    if detected_language == "thanglish":
        if not (explanation.startswith("Understood —") or explanation.startswith("Understood -")):
            explanation = f"Understood — {explanation}"
    elif detected_language == "tamil":
        explanation = f"வினவல் வெற்றிகரமாக செயல்படுத்தப்பட்டது — கொடுக்கப்பட்ட நிபந்தனைக்கு ஏற்ற தகவல்கள் எதுவும் கிடைக்கவில்லை."

    return explanation


