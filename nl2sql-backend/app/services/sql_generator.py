import copy
import difflib
import hashlib
import json
import logging
import re
import socket
import time
import warnings
from typing import Dict, Any, Optional, List, Union, Tuple
import sqlglot
from sqlglot import exp

# Set global default socket timeout so TLS handshakes / REST calls never block indefinitely
socket.setdefaulttimeout(30.0)

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
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
]

# Sticky working model pointer to avoid fallback delays on every call
_WORKING_MODEL: str = "gemini-3.1-flash-lite"

# Common query command verbs that must NEVER be treated as entity search values
COMMON_COMMAND_VERBS = {
    "give", "show", "list", "get", "find", "tell", "fetch", "display",
    "select", "return", "provide", "search", "check", "view", "count",
    "filter", "print", "lookup", "query", "see", "bring", "pull", "ask"
}

# Standard stop words for isolating search terms
QUERY_STOP_WORDS = {
    "show", "me", "list", "get", "find", "all", "the", "of", "for", "with", "in",
    "by", "on", "at", "to", "a", "an", "is", "are", "was", "were", "who", "whose",
    "details", "record", "records", "search", "query", "check", "info", "information",
    "patient", "patients", "doctor", "doctors", "customer", "customers", "order", "orders",
    "product", "products", "appointment", "appointments", "department", "departments",
    "category", "categories", "review", "reviews", "table", "tables", "database", "databases",
    "db", "schema", "schemas", "row", "rows", "column", "columns", "dataset", "datasets",
    "view", "views", "data", "value", "values", "entity", "entities", "please", "can", "you",
    "give", "tell", "view", "see", "display", "named", "called", "name", "names", "about",
    "age", "ages", "gender", "genders", "id", "ids", "status", "statuses", "diagnosis",
    "from", "between", "and", "or", "not", "date", "dates", "month", "year",
    "which", "what", "where", "how", "many", "much", "having", "than", "more", "less",
    # Tamil / Tanglish verbs, pronouns, and structural keywords
    "enaku", "enakku", "kodu", "koduu", "kudu", "kudunga", "tharu", "tharuga", "kaatu",
    "kaattu", "kaatunga", "sollu", "solu", "sollunga", "paaru", "paarunga", "irukku",
    "irukka", "vendum", "venum", "pathina", "patriya", "patri", "oda", "la", "ku",
    "irunthu", "ella", "ellam", "ellame", "ethana", "evvalavu", "yaar", "enna", "enga",
    "eppadi", "eppo", "nalla", "mattum", "tha", "thanga", "thaanga", "pannu", "pannunga",
}

MONTH_NAMES = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December"
}

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


def detect_conversational_intent(
    nl_question: str,
    schema: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Detect purely conversational messages (greetings, 'what can you do?', 'tell me a joke', 'who made you?')
    that do not involve querying the database.
    Returns a dict with intent='conversation', data_available=False, sql=None, and a friendly explanation with sample questions,
    or None if the question appears to be a database query.
    """
    if not nl_question or not nl_question.strip():
        return None

    q_raw = nl_question.strip()
    q_lower = q_raw.lower()
    q_clean = re.sub(r"[^\w\s]", " ", q_lower)
    words = q_clean.split()
    if not words:
        return None

    # Database keywords that indicate query intent
    db_keywords = {
        "select", "show", "list", "find", "get", "give", "display", "fetch",
        "how", "many", "count", "average", "avg", "sum", "total", "min", "max",
        "minimum", "maximum", "filter", "where", "between", "top", "best", "worst",
        "delete", "update", "insert", "drop", "alter", "records", "rows", "table",
        "tables", "column", "columns", "database", "schema", "patient", "patients",
        "doctor", "doctors", "appointment", "appointments", "customer", "customers",
        "order", "orders", "product", "products", "diagnosis", "admitted", "admission",
        "prescribe", "prescription", "salary", "age", "gender", "name", "price", "cost",
        "revenue", "sales", "status", "bill", "billing", "department", "departments"
    }

    # If any word in query matches known schema table or column names, not pure conversation
    if schema:
        for tbl_name, cols in schema.items():
            db_keywords.add(tbl_name.lower())
            if isinstance(cols, list):
                for col in cols:
                    if isinstance(col, dict) and "name" in col:
                        db_keywords.add(col["name"].lower())

    # Check if any database keywords are present
    has_db_intent = any(w in db_keywords for w in words)
    if has_db_intent:
        return None

    # Pure conversational patterns
    is_greeting = q_clean.strip() in {
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "howdy", "hola", "vanakkam", "namaste", "greetings", "sup", "yo", "hi there", "hello there"
    } or (len(words) <= 2 and words[0] in {"hi", "hello", "hey", "vanakkam", "namaste"})

    is_capability = any(phrase in q_clean for phrase in [
        "what can you do", "what do you do", "help me", "how to use", "what is this",
        "who are you", "what are your features", "what are your capabilities", "can you help"
    ]) or q_clean.strip() == "help"

    is_chitchat = any(phrase in q_clean for phrase in [
        "tell me a joke", "make me laugh", "say a joke", "how are you", "how are you doing",
        "thank you", "thanks", "thanks a lot", "thank u", "bye", "goodbye", "see you", "good night"
    ])

    is_creator = any(phrase in q_clean for phrase in [
        "who made you", "who created you", "who built you", "who developed you"
    ])

    if not (is_greeting or is_capability or is_chitchat or is_creator):
        return None

    # Formulate friendly response
    tables = list(schema.keys()) if schema else []
    sample_queries = []
    if tables:
        for t in tables[:3]:
            sample_queries.append(f"• 'Show all {t}'")
        sample_queries.append(f"• 'How many {tables[0]} are there?'")
    else:
        sample_queries = [
            "• 'How many records are in the database?'",
            "• 'List all tables'",
        ]
    samples_str = "\n".join(sample_queries)

    if is_creator:
        explanation = (
            "I was created as an AI-powered Database Assistant to help you explore and query "
            f"your data using natural language. Try asking questions like:\n{samples_str}"
        )
    elif "joke" in q_clean:
        explanation = (
            "Why do database administrators make great DJs? Because they always know how to drop the tables! 😄\n\n"
            f"Whenever you're ready, feel free to ask questions about your data, such as:\n{samples_str}"
        )
    elif any(th in q_clean for th in ["thank", "bye", "goodbye", "good night"]):
        explanation = "You're very welcome! Feel free to ask anytime you need data insights. Have a wonderful day!"
    elif "how are you" in q_clean:
        explanation = (
            "I'm doing great, thank you! Ready to help you query and analyze your data. "
            f"Here are a few things you can ask:\n{samples_str}"
        )
    else:
        explanation = (
            "Hello! I am your AI Database Assistant. I can help you search, summarize, and visualize data "
            f"from your connected database using natural language. Here are some examples you can try:\n{samples_str}"
        )

    return {
        "data_available": False,
        "intent": "conversation",
        "unavailable_message": None,
        "corrected_terms": [],
        "needs_clarification": False,
        "clarification_question": None,
        "interpreted_text": q_raw,
        "query_type": "conversation",
        "sql": None,
        "result": [],
        "explanation": explanation,
        "confidence": 1.0,
        "detected_language": detect_input_language(q_raw),
    }


def detect_sql_injection_attempt(nl_question: str) -> Optional[Dict[str, Any]]:
    """Detect explicit SQL injection attempts or dangerous DDL commands in input text."""
    if not nl_question or not isinstance(nl_question, str):
        return None
    q = nl_question.strip().lower()

    # DDL patterns
    if re.search(r"\bdrop\s+(?:table|database|schema)\b", q) or re.search(r"\btruncate\s+(?:table)?\b", q):
        return {
            "data_available": True,
            "needs_clarification": False,
            "clarification_question": None,
            "sql": None,
            "explanation": "Schema modification or destructive operations (such as DROP TABLE or DROP DATABASE) are strictly prohibited.",
            "confidence": 0.0,
            "query_type": "select",
            "result": [],
            "interpreted_text": nl_question,
            "detected_language": "english",
        }

    # Tautology injection patterns e.g. ' OR 1=1, ' OR '1'='1, 1=1;
    if (
        re.search(r"(?:'|\")\s*or\s+['\"]?1['\"]?\s*=\s*['\"]?1", q)
        or re.search(r"\b1\s*=\s*1\s*;", q)
        or re.search(r";\s*drop\b", q)
        or re.search(r"where\s+1\s*=\s*1\s*;", q)
        or re.search(r"or\s+1\s*=\s*1\s*--", q)
    ):
        return {
            "data_available": True,
            "needs_clarification": False,
            "clarification_question": None,
            "sql": None,
            "explanation": "Potential SQL injection attack pattern detected and blocked for database security.",
            "confidence": 0.0,
            "query_type": "select",
            "result": [],
            "interpreted_text": nl_question,
            "detected_language": "english",
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
    "age", "ages", "name", "names", "gender", "male", "female", "older", "younger", "above", "below",
    "greater", "less", "more", "between", "diagnosis", "disease", "condition",
    "diabetic", "diabetes", "hypertensive", "hypertension", "fever", "cancer",
    "admitted", "admission", "date", "dates", "status", "scheduled", "completed", "cancelled",
    "count", "average", "avg", "sum", "total", "top", "limit", "min", "max",
    "department", "salary", "price", "cost", "bill", "billing", "paid", "unpaid",
    "amount", "years", "year", "months", "month", "days", "day",
    "column", "columns", "field", "fields", "email", "city", "specialty", "phone"
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

    # Reject queries asking for all entities (e.g. "all patients", "all doctors", "all customers")
    if re.search(r"\b(?:all|every)\s+(?:patients?|doctors?|customers?|products?|records?|rows?)\b", q_lower):
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


def get_and_conjuncts(node):
    """Recursively extract all conjuncts in an AND tree."""
    if node is None:
        return []
    if isinstance(node, exp.Paren):
        return get_and_conjuncts(node.this)
    if isinstance(node, exp.And):
        return get_and_conjuncts(node.this) + get_and_conjuncts(node.expression)
    return [node]


def build_and_tree(conjuncts):
    """Rebuild an AND tree from a list of conjuncts."""
    if not conjuncts:
        return None
    res = conjuncts[0]
    for c in conjuncts[1:]:
        res = exp.And(this=res, expression=c)
    return res


def extract_col_and_literal(pred):
    """If pred is col = literal (or literal = col), return (col_expr, norm_col_key, literal_expr).
    Handles LOWER(col), table.col, quoted identifiers.
    """
    if not isinstance(pred, exp.EQ):
        return None
    left, right = pred.this, pred.expression

    col_expr = None
    lit_expr = None

    if isinstance(right, exp.Literal):
        lit_expr = right
        col_expr = left
    elif isinstance(left, exp.Literal):
        lit_expr = left
        col_expr = right
    else:
        return None

    # Check if col_expr is a Column, or Lower(Column), or similar deterministic expression
    is_valid_col = False
    if isinstance(col_expr, exp.Column):
        is_valid_col = True
    elif isinstance(col_expr, exp.Lower) and isinstance(col_expr.this, exp.Column):
        is_valid_col = True

    if not is_valid_col:
        return None

    norm_col_key = col_expr.sql(dialect="sqlite").lower()
    return col_expr, norm_col_key, lit_expr


def rewrite_and_group(node, notes_list):
    """Walk an AND group and rewrite multiple equality predicates on the same column into an IN condition."""
    conjuncts = get_and_conjuncts(node)
    if len(conjuncts) < 2:
        return node

    col_preds = {}
    for idx, c in enumerate(conjuncts):
        info = extract_col_and_literal(c)
        if info:
            col_expr, norm_key, lit_expr = info
            col_preds.setdefault(norm_key, []).append((idx, col_expr, lit_expr))

    rewritten_indices = set()
    new_in_predicates = []

    for norm_key, pred_list in col_preds.items():
        if len(pred_list) >= 2:
            lit_sql_set = {lit.sql(dialect="sqlite") for _, _, lit in pred_list}
            if len(lit_sql_set) >= 2:
                # Unsatisfiable col = a AND col = b condition found!
                first_col_expr = pred_list[0][1]
                unique_lits = []
                seen_lits = set()
                for _, _, lit in pred_list:
                    l_sql = lit.sql(dialect="sqlite")
                    if l_sql not in seen_lits:
                        seen_lits.add(l_sql)
                        unique_lits.append(lit)

                in_node = exp.In(this=first_col_expr.copy(), expressions=[l.copy() for l in unique_lits])
                new_in_predicates.append(in_node)
                for idx, _, _ in pred_list:
                    rewritten_indices.add(idx)

                val_reprs = " and ".join(str(l.this) for l in unique_lits)
                notes_list.append(f"Treated '{val_reprs}' as either value")

    if not rewritten_indices:
        return node

    remaining = [c for idx, c in enumerate(conjuncts) if idx not in rewritten_indices]
    combined = remaining + new_in_predicates
    return build_and_tree(combined)


def sanitize_mutually_exclusive_and(sql: str, explanation: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Deterministic AST guard using sqlglot to walk all WHERE, JOIN ON, subqueries,
    and nested OR/AND groups.
    If the SAME column has 2+ equality predicates against DIFFERENT literals inside one AND group,
    that condition is unsatisfiable. Rewrites them to col IN (v1, v2, ...) and adds a note
    to the explanation ('Treated 'X and Y' as either value').
    Preserves satisfiable conditions: col > 5 AND col < 10, LIKE '%a%' AND LIKE '%b%',
    different columns, intersection queries with GROUP BY/HAVING.
    """
    if not sql or (" AND " not in sql.upper() and " and " not in sql):
        return sql, explanation

    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        # Graceful fallback to regex if sqlglot parse fails on unconventional syntax
        return _regex_fallback_mutually_exclusive_and(sql, explanation)

    notes = []

    def transform_clause(clause_node):
        if not clause_node:
            return clause_node
        def visitor(node):
            if isinstance(node, exp.And):
                return rewrite_and_group(node, notes)
            return node
        return clause_node.transform(visitor)

    for select in tree.find_all(exp.Select):
        if select.args.get("where"):
            select.args["where"].set("this", transform_clause(select.args["where"].this))
        for join in select.args.get("joins") or []:
            if join.args.get("on"):
                join.args["on"] = transform_clause(join.args["on"])

    rewritten_sql = tree.sql(dialect="sqlite")

    # Update explanation if any note was generated
    updated_explanation = explanation
    if notes:
        unique_notes = []
        for n in notes:
            if n not in unique_notes:
                unique_notes.append(n)
        notes_str = "; ".join(unique_notes)
        if updated_explanation:
            if notes_str not in updated_explanation:
                updated_explanation = f"{updated_explanation.rstrip('.')} ({notes_str})."
        else:
            updated_explanation = f"Query executed successfully ({notes_str})."

    return rewritten_sql, updated_explanation


def _regex_fallback_mutually_exclusive_and(sql: str, explanation: Optional[str] = None) -> Tuple[str, Optional[str]]:
    pattern = r"((?:LOWER\s*\(\s*)?(\w+)(?:\s*\))?\s*=\s*(?:'[^']*'|\d+))\s+AND\s+((?:LOWER\s*\(\s*)?\2(?:\s*\))?\s*=\s*(?:'[^']*'|\d+))"
    current = sql
    changed = False
    for _ in range(5):
        new_sql = re.sub(pattern, r"\1 OR \3", current, flags=re.IGNORECASE)
        if new_sql != current:
            changed = True
            current = new_sql
        else:
            break
    exp_out = explanation
    if changed:
        note = "Treated values as either value"
        if exp_out:
            if note not in exp_out:
                exp_out = f"{exp_out.rstrip('.')} ({note})."
        else:
            exp_out = f"Query executed successfully ({note})."
    return current, exp_out


def fix_mutually_exclusive_and(sql: str) -> str:
    """Detect and rewrite mutually exclusive AND conditions on the same column into OR.
    
    Preserved for backward-compatibility with existing tests.
    """
    if not sql or " AND " not in sql:
        return sql

    pattern = r"((?:LOWER\s*\(\s*)?(\w+)(?:\s*\))?\s*=\s*(?:'[^']*'|\d+))\s+AND\s+((?:LOWER\s*\(\s*)?\2(?:\s*\))?\s*=\s*(?:'[^']*'|\d+))"
    
    current = sql
    for _ in range(5):
        new_sql = re.sub(pattern, r"\1 OR \3", current, flags=re.IGNORECASE)
        if new_sql != current:
            current = new_sql
        else:
            break
            
    return current


def extract_where_filter_values(sql: str) -> List[Tuple[str, List[Any]]]:
    """Parse SQL and extract target column and literal values from WHERE clause."""
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return []

    where = tree.find(exp.Where)
    if not where:
        return []

    results = []
    # 1. In expressions: col IN (val1, val2, ...)
    for in_expr in where.find_all(exp.In):
        col = in_expr.this
        col_name = col.sql(dialect="sqlite")
        vals = [e.this if isinstance(e, exp.Literal) else e.sql(dialect="sqlite") for e in (in_expr.expressions or [])]
        results.append((col_name, vals))

    # 2. Equality expressions inside OR / AND
    if not results:
        eq_map = {}
        for eq in where.find_all(exp.EQ):
            left, right = eq.this, eq.expression
            col, lit = None, None
            if isinstance(right, exp.Literal):
                lit = right.this
                col = left
            elif isinstance(left, exp.Literal):
                lit = left.this
                col = right
            if col and lit is not None:
                col_name = col.sql(dialect="sqlite")
                eq_map.setdefault(col_name, []).append(lit)
        for col_name, vals in eq_map.items():
            results.append((col_name, vals))

    return results


def evaluate_where_clause_results(
    sql: str,
    exec_result: List[Dict[str, Any]],
    question: str,
) -> Optional[str]:
    """Inspect the executed SQL WHERE clause to check multi-value satisfaction.
    If some requested values were found and others were not, return an explanation like:
    'Found transaction TXN_1001; no transaction TXN_1002 found.'
    """
    if not sql or not exec_result:
        return None

    filter_info = extract_where_filter_values(sql)
    if not filter_info:
        return None

    for col_expr, requested_vals in filter_info:
        if len(requested_vals) >= 2:
            col_clean = re.sub(r"^(?:LOWER|UPPER|TRIM)\s*\(\s*", "", col_expr, flags=re.IGNORECASE).rstrip(")")
            col_base = col_clean.split(".")[-1].strip('"`[] ')
            clean_req = [str(v).strip("'\"") for v in requested_vals]
            found = []
            missing = []

            for target in clean_req:
                target_l = target.lower()
                is_found = False
                for row in exec_result:
                    if col_base in row and str(row[col_base]).lower() == target_l:
                        is_found = True
                        break
                    for k, val in row.items():
                        if str(val).lower() == target_l:
                            is_found = True
                            break
                    if is_found:
                        break
                if is_found:
                    found.append(target)
                else:
                    missing.append(target)

            if found and missing:
                entity_label = col_base.replace("_", " ").replace(" id", "").strip()
                if not entity_label or entity_label in ("id", "name"):
                    q_l = question.lower()
                    for candidate in ("transaction", "customer", "product", "order", "patient", "doctor", "item"):
                        if candidate in q_l:
                            entity_label = candidate
                            break
                    if not entity_label or entity_label in ("id", "name"):
                        entity_label = "record"

                found_str = ", ".join(found)
                missing_str = ", ".join(missing)
                return f"Found {entity_label} {found_str}; no {entity_label} {missing_str} found."

    return None


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

    # Do not check near-miss for obvious criteria / aggregations / temporal filters / pattern searches
    criteria_keywords = {
        "day", "days", "month", "months", "year", "years", "week", "weeks",
        "older", "younger", "greater", "less", "more", "between", "visited",
        "admitted", "how many", "count", "average", "avg", "sum", "total",
        "highest", "lowest", "most", "least", "top", "contains", "containing",
        "starts", "starting", "ends", "ending", "like"
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
    stop_words = QUERY_STOP_WORDS

    prefix_pattern = r"^(?:show|list|get|find|search\s+for|view|display|details\s+of|enaku|enakku|kodu|kudu|tharu|kaatu|kaattu)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:patients?|doctors?|customers?|products?|orders?|records?|details?|info)?\s*(?:of\s+)?(?:patients?|doctors?|customers?|products?|orders?|records?|details?|info)?\s*(?:named|called|for|with)?\s*"
    candidate_phrase = re.sub(prefix_pattern, "", nl_question.strip(), flags=re.IGNORECASE).strip()
    schema_cols = set()
    schema_tables = set()
    if schema:
        for tbl, cols in schema.items():
            t_low = tbl.lower()
            schema_tables.add(t_low)
            schema_tables.add(t_low.rstrip("s"))
            if t_low.endswith("ies"):
                schema_tables.add(t_low[:-3] + "y")
            schema_tables.add(t_low + "s")
            schema_tables.add(t_low + "es")

            if isinstance(cols, list):
                for c in cols:
                    c_name = c.get("name", "") if isinstance(c, dict) else str(c)
                    schema_cols.add(c_name.lower())
                    schema_cols.add(c_name.lower() + "s")

    candidate_tokens = [
        w for w in re.findall(r"\b[a-zA-Z0-9_]+\b", nl_question)
        if w.lower() not in stop_words
        and w.lower() not in schema_cols
        and w.lower() not in schema_tables
        and len(w) >= 3
    ]

    # If candidate phrase is composed entirely of stop words or schema tables/columns, ignore it
    candidate_phrase_words = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_]+\b", candidate_phrase)]
    if not candidate_phrase_words or all(w in stop_words or w in schema_cols or w in schema_tables for w in candidate_phrase_words):
        candidate_phrase = ""

    # Check for exact matches first: if exact match exists anywhere in question or candidate phrase, no confirmation needed
    q_norm = " " + re.sub(r"[^\w\s]", " ", nl_question.lower()) + " "
    q_norm = re.sub(r"\s+", " ", q_norm)
    for s_val, _ in unique_samples:
        s_clean = " " + re.sub(r"[^\w\s]", " ", s_val.lower()) + " "
        s_clean = re.sub(r"\s+", " ", s_clean)
        if s_clean in q_norm:
            return None

        core_val = get_core_person_name(s_val)
        if core_val and len(core_val) >= 3:
            core_clean = " " + re.sub(r"[^\w\s]", " ", core_val.lower()) + " "
            core_clean = re.sub(r"\s+", " ", core_clean)
            if core_clean in q_norm:
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
    if candidate_phrase and len(candidate_phrase) >= 3 and candidate_phrase.lower() not in stop_words and candidate_phrase.lower() not in schema_tables:
        search_terms.append(candidate_phrase)
    for t in candidate_tokens:
        if t not in search_terms and t.lower() not in schema_tables and t.lower() not in stop_words:
            search_terms.append(t)

    for term in search_terms:
        term_lower = term.lower()
        if term_lower in stop_words or term_lower in schema_cols or term_lower in schema_tables:
            continue
        if len(term_lower) < 3:
            continue

        best_match = None
        best_score = 0.0
        min_threshold = 0.85 if len(term_lower) <= 5 else 0.80

        for s_val, is_name in unique_samples:
            s_lower = s_val.lower()
            s_words = [w.lower() for w in s_val.split()]

            # 1. Exact single-word match in a multi-word sample (only for person names, e.g. 'harini' -> 'Harini Krishnan')
            if term_lower in s_words:
                if is_name and len(s_words) > 1 and len(term_lower) >= 4:
                    return (term, s_val)
                # Exact word match for attributes (e.g. 'diabetes') is a valid query, not a typo
                continue

            # 2. Substring match for person names (e.g. 'harini' in 'Harini Krishnan')
            if is_name and len(term_lower) >= 5 and term_lower in s_lower:
                return (term, s_val)

            # 3. Fuzzy similarity against individual words in the sample value
            for w in s_words:
                if term_lower == w:
                    continue
                # Length guard: skip comparison if lengths differ significantly
                if abs(len(term_lower) - len(w)) > 2:
                    continue
                sim = difflib.SequenceMatcher(None, term_lower, w).ratio()
                if sim >= min_threshold and sim < 1.0 and sim > best_score:
                    best_score = sim
                    best_match = s_val

            # 4. Fuzzy similarity against full sample value
            if term_lower != s_lower and abs(len(term_lower) - len(s_lower)) <= 3:
                full_sim = difflib.SequenceMatcher(None, term_lower, s_lower).ratio()
                if full_sim >= min_threshold and full_sim < 1.0 and full_sim > best_score:
                    best_score = full_sim
                    best_match = s_val

        if best_match and best_score >= min_threshold:
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
                "query_type": "conversation",
                "intent": "conversation",
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
    # Security check: detect injection attempts and schema destructive commands
    # ---------------------------------------------------------------------------
    injection_resp = detect_sql_injection_attempt(nl_question)
    if injection_resp:
        return injection_resp

    # ---------------------------------------------------------------------------
    # Conversational intent check: greetings, capabilities, chitchat (no DB query)
    # ---------------------------------------------------------------------------
    conv_intent = detect_conversational_intent(nl_question, session.get("schema", {}))
    if conv_intent:
        return conv_intent

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
    # Direct table request fast path (e.g. "enaku customer table kodu", "customers table", "show patient table")
    if schema:
        words = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_]+\b", nl_question)]
        meaningful_words = [w for w in words if w not in QUERY_STOP_WORDS]
        filter_indicators = {
            "where", "filter", "when", "with", "having", "count", "avg", "average",
            "sum", "total", "min", "max", "top", "limit", "older", "younger",
            "greater", "less", "more", "price", "cost", "status", "active",
            "admitted", "discharged", "appointment", "prescribe", "visit", "billing",
            "than", "between", "like", "contains"
        }
        if meaningful_words and not set(words).intersection(filter_indicators):
            matched_table = None
            for tbl in schema.keys():
                t_clean = tbl.lower()
                tbl_variations = {t_clean, t_clean.rstrip("s"), t_clean + "s", t_clean + "es"}
                if t_clean.endswith("ies"):
                    tbl_variations.add(t_clean[:-3] + "y")
                if any(w in tbl_variations for w in meaningful_words):
                    remaining = [w for w in meaningful_words if w not in tbl_variations]
                    if not remaining:
                        matched_table = tbl
                        break
            if matched_table:
                logger.info("Direct whole-table query resolved for table '%s' from question '%s'", matched_table, nl_question)
                sql = f"SELECT * FROM {matched_table};"
                exp = f"Retrieves all records from the {matched_table} table."
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
                    "confidence": 0.98,
                    "detected_language": detect_input_language(nl_question),
                    "relevant_tables": [matched_table],
                }
                _put_in_cache(cache_key, data)
                return data


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
   - If the current user question is a follow-up, refinement, or pivot:
     - Interpret it directly in the context of the previous query and generate the SQL. DO NOT ask for clarification if the follow-up can refine or pivot the previous query!
     - Filtering refinements (e.g. previous was "Show all doctors" and current is "in Cardiology"): refine the previous query: SELECT * FROM doctors WHERE LOWER(specialty) = 'cardiology';
     - Entity pivots (e.g. previous was "Count patients" and current is "what about doctors?"): apply the same aggregate to the new entity: SELECT COUNT(*) FROM doctors;
     - Set "needs_clarification": false, generate valid SQLite in "sql", provide a clear "explanation", confidence >= 0.85.
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

7. Multi-Value Filtering and Conjunction Rules (STRICT LOGIC):
   a. SAME-COLUMN MULTI-VALUE UNION (CRITICAL):
      - Two or more values for the SAME column joined by "and", "or", "&", a comma, "with", or Tamil/Thanglish equivalents ("matrum", "mattum", "um", "mathiri", "kooda") mean a UNION of values:
        Use: col IN (...) or (col = v1 OR col = v2).
        NEVER generate: col = v1 AND col = v2 (impossible: a single database row cannot have two distinct values in the same column, and will return 0 rows!).
      - This rule applies universally across ANY column type: numeric IDs, text IDs/codes, names, dates, amounts, categories, or statuses.
      - Support any number of values (from 2 up to 50 values) and mixed comma-and forms in one question (e.g., "ids 1, 2 and 5", "names Ravi, Priya and Amit").
      - If entities might be numeric IDs or names (e.g. 'customer 1 and customer 2'), support both: WHERE id IN (1, 2) OR LOWER(name) IN ('customer 1', 'customer 2').
   b. CONDITIONS ON DIFFERENT COLUMNS (LOGICAL AND):
      - Conditions on DIFFERENT columns joined by "and" mean logical AND (e.g., "customers in Chennai and age above 30" -> WHERE city = 'Chennai' AND age > 30).
      - Mixed questions combining same-column choices and different-column criteria must group properly with parentheses:
        e.g., "customer 1 or 2 and city Chennai" -> WHERE id IN (1, 2) AND city = 'Chennai'.
   c. SET INTERSECTION OVER MULTIPLE ROWS:
      - Phrasings like "both X and Y" or "customers who bought product A and product B" represent a set INTERSECTION across multiple rows.
      - Use aggregation with GROUP BY and HAVING COUNT(DISTINCT ...) or INTERSECT:
        e.g., SELECT customer_id FROM orders WHERE product_id IN ('A', 'B') GROUP BY customer_id HAVING COUNT(DISTINCT product_id) = 2;
        or ask a short clarification if ambiguous.
   d. NEGATION, EXCLUSIONS, AND RANGES:
      - "not X", "except X", "other than X" (e.g., "everyone except customer 1 and 2") mean NOT IN / !=:
        e.g., WHERE id NOT IN (1, 2).
      - "between A and B" or "from A to B" represents a continuous numerical or date range (e.g. amount BETWEEN 100 AND 250, or col >= 100 AND col <= 250).
        The "and" inside a BETWEEN clause connects range bounds and MUST NEVER be split or transformed into an IN list.
   e. TEXT VALUES & DATA INTEGRITY:
      - Use case-insensitive matching for text comparisons: LOWER(col) IN ('a', 'b') or (LOWER(col) = 'a' OR LOWER(col) = 'b').
      - Maintain the strict literal data value rule: retain the exact text literal values typed by the user.

8. Date & Time Filtering Rules:
   - Several distinct dates mean IN or OR on the date column:
     e.g., "orders on 2024-02-01 and 2024-02-03" -> WHERE order_date IN ('2024-02-01', '2024-02-03').
   - "from A to B" and "between A and B" mean a continuous range:
     e.g., appointment_date BETWEEN '2024-02-01' AND '2024-02-05'.
   - When the user asks for records by month or date range WITHOUT specifying a year (e.g., "appointment date between January and February", "orders in March", "January and February"):
     - Do NOT assume the current year or any specific year.
     - You MUST match by month across ALL years using SQLite strftime('%m', date_column):
       e.g., strftime('%m', appointment_date) BETWEEN '01' AND '02'
       e.g., strftime('%m', order_date) IN ('01', '02')
       (Two-digit month numbers: '01'=Jan, '02'=Feb, '03'=Mar, ..., '12'=Dec).
     - In the "explanation" field, you MUST explicitly state: "no year given, so all years were included".
   - When the user specifies an explicit year (e.g. "January 2024", "between Jan and Feb 2024", "in 2024"):
     - Filter on that specific year:
       e.g., appointment_date BETWEEN '2024-01-01' AND '2024-02-29'
       or strftime('%Y', appointment_date) = '2024' AND strftime('%m', appointment_date) BETWEEN '01' AND '02'.
   - For relative date terms:
     - "last 30 days": date_column >= date('now', '-30 days')
     - "this year": strftime('%Y', date_column) = strftime('%Y', 'now')

9. Output Structure Rules:
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
                    data["sql"], data["explanation"] = sanitize_mutually_exclusive_and(data["sql"], data.get("explanation"))
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
6. Same-column multi-value rule: Two or more values for the SAME column joined by 'and', 'or', commas mean col IN (...) or OR. Never col = a AND col = b. Different columns use AND. Ranges use BETWEEN.

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
                retry_res = model.generate_content(
                    retry_prompt,
                    generation_config=gen_config,
                    request_options={"timeout": 30.0},
                )
                retry_cleaned = _clean_json_string(retry_res.text or "")
                retry_data = json.loads(retry_cleaned)
                if retry_data.get("sql"):
                    retry_data["sql"], retry_data["explanation"] = sanitize_mutually_exclusive_and(retry_data["sql"], retry_data.get("explanation"))
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

    # Deterministic query resolution for common patterns when LLM times out or is overloaded
    q_lower = nl_question.lower()
    if filtered_schema:
        if "patients" in filtered_schema:
            m_older = re.search(r"(?:older than|age\s*(?:>|over|greater than|above))\s*(\d+)", q_lower)
            m_younger = re.search(r"(?:younger than|age\s*(?:<|under|less than|below))\s*(\d+)", q_lower)
            if m_older:
                val = m_older.group(1)
                return {
                    "data_available": True,
                    "unavailable_message": None,
                    "corrected_terms": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "interpreted_text": nl_question,
                    "query_type": "select",
                    "sql": f"SELECT * FROM patients WHERE age > {val};",
                    "explanation": f"Retrieves all patients older than {val} years from the patients table.",
                    "confidence": 0.95,
                    "detected_language": detected_lang,
                    "relevant_tables": ["patients"],
                }
            elif m_younger:
                val = m_younger.group(1)
                return {
                    "data_available": True,
                    "unavailable_message": None,
                    "corrected_terms": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "interpreted_text": nl_question,
                    "query_type": "select",
                    "sql": f"SELECT * FROM patients WHERE age < {val};",
                    "explanation": f"Retrieves all patients younger than {val} years from the patients table.",
                    "confidence": 0.95,
                    "detected_language": detected_lang,
                    "relevant_tables": ["patients"],
                }
            elif "count" in q_lower and "patient" in q_lower:
                return {
                    "data_available": True,
                    "unavailable_message": None,
                    "corrected_terms": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "interpreted_text": nl_question,
                    "query_type": "select",
                    "sql": "SELECT COUNT(*) FROM patients;",
                    "explanation": "Calculates the total number of patients in the patients table.",
                    "confidence": 0.95,
                    "detected_language": detected_lang,
                    "relevant_tables": ["patients"],
                }
            elif any(w in q_lower for w in ["all patients", "list patients", "show patients"]):
                return {
                    "data_available": True,
                    "unavailable_message": None,
                    "corrected_terms": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "interpreted_text": nl_question,
                    "query_type": "select",
                    "sql": "SELECT * FROM patients;",
                    "explanation": "Retrieves all patient records from the patients table.",
                    "confidence": 0.95,
                    "detected_language": detected_lang,
                    "relevant_tables": ["patients"],
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
        if data.get("intent") == "conversation" or data.get("query_type") == "conversation":
            data["sql"] = None
            data["needs_clarification"] = False
            data["clarification_question"] = None
            data["unavailable_message"] = None
            data["intent"] = "conversation"
            data["query_type"] = "conversation"
            if not data.get("explanation"):
                data["explanation"] = "Hello! I am your AI Database Assistant. How can I help you query your database?"
            try:
                conf = float(data.get("confidence", 1.0))
                data["confidence"] = conf
            except (ValueError, TypeError):
                data["confidence"] = 1.0
        else:
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

    # Additional safety net: Check if SQL WHERE clause substituted an entity name search value
    # (e.g. user asked for 'virthi', but SQL substituted 'Karthik')
    if data.get("sql") and nl_question:
        sql_str = data["sql"]
        q_tokens = re.findall(r"\b[a-zA-Z0-9_']+\b", nl_question)
        candidate_user_terms = [
            w for w in q_tokens
            if w.lower() not in QUERY_STOP_WORDS
            and w.lower() not in COMMON_COMMAND_VERBS
            and not _is_schema_term(w)
            and not w.isdigit()
            and len(w) >= 3
        ]
        sql_literals = re.findall(r"['\"]%?([^%'\"]+)%?['\"]", sql_str)
        for lit in sql_literals:
            lit_lower = lit.lower()
            # NEVER touch dates, month strings, numbers, booleans, or common status/gender values
            if (
                re.match(r"^\d{4}", lit)
                or re.match(r"^\d{1,2}$", lit)
                or lit_lower in ("completed", "scheduled", "cancelled", "active", "male", "female", "yes", "no", "true", "false")
            ):
                continue
            if _is_data_value(lit_lower) and not _is_schema_term(lit_lower):
                if lit_lower not in nl_question.lower():
                    for qw in candidate_user_terms:
                        qw_lower = qw.lower()
                        if qw_lower not in sql_str.lower():
                            ratio = difflib.SequenceMatcher(None, qw_lower, lit_lower).ratio()
                            is_entity_target = bool(re.search(rf"\b(?:patient|doctor|customer|product|named|name)\s+{re.escape(qw)}\b", nl_question, re.IGNORECASE))
                            if ratio >= 0.45 or is_entity_target:
                                logger.warning(
                                    "[Safety Net] Silent name substitution detected: '%s' in SQL replaced user term '%s'. Reverting SQL to user literal.",
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
        explanation = (data.get("explanation") or "").strip()
        is_blocked = (
            "prohibit" in explanation.lower()
            or "forbidden" in explanation.lower()
            or "not allowed" in explanation.lower()
            or "blocked" in explanation.lower()
            or "destructive" in explanation.lower()
            or any(k in nl_question.lower() for k in ("drop table", "drop database", "truncate table", "delete all", "update all"))
        )

        if not sql or not isinstance(sql, str) or not sql.strip():
            if is_blocked:
                data["needs_clarification"] = False
                data["clarification_question"] = None
                data["sql"] = None
                data["explanation"] = explanation or "Database schema destruction or unrestricted modification is strictly prohibited."
                data["confidence"] = 0.0
            else:
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
            response = model.generate_content(
                prompt,
                generation_config=gen_config,
                request_options={"timeout": 30.0},
            )
            raw_text = response.text or ""
            cleaned = _clean_json_string(raw_text)

            try:
                data = json.loads(cleaned)
                if data.get("sql"):
                    data["sql"], data["explanation"] = sanitize_mutually_exclusive_and(data["sql"], data.get("explanation"))
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
                retry_res = model.generate_content(
                    retry_prompt,
                    generation_config=gen_config,
                    request_options={"timeout": 30.0},
                )
                retry_cleaned = _clean_json_string(retry_res.text or "")
                retry_data = json.loads(retry_cleaned)
                if retry_data.get("sql"):
                    retry_data["sql"], retry_data["explanation"] = sanitize_mutually_exclusive_and(retry_data["sql"], retry_data.get("explanation"))
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
    elif "transaction" in q_lower or "transactions" in q_lower or "transactions" in sql_lower:
        entity = "transaction"
        entity_plural = "transactions"
    elif "item" in q_lower or "items" in q_lower:
        entity = "item"
        entity_plural = "items"
    else:
        entity = "record"
        entity_plural = "records"

    # 2. Extract WHERE clause from executed SQL
    where_match = re.search(r"\bWHERE\b(.*?)(?:\bORDER\s+BY\b|\bGROUP\s+BY\b|\bLIMIT\b|;|\Z)", sql, re.IGNORECASE | re.DOTALL)
    where_clause = where_match.group(1).strip() if where_match else ""

    specific_search_val = None
    is_name_search = False
    explanation = None

    if where_clause:
        # Multi-value or single-value filter extraction via sqlglot
        filter_info = extract_where_filter_values(sql)
        for col_expr, requested_vals in filter_info:
            col_l = col_expr.lower()
            if "strftime" in col_l or "date(" in col_l:
                continue
            clean_vals = [
                str(v).strip("'\"") for v in requested_vals
                if str(v).strip("'\"") and str(v).strip("'\"").lower() not in COMMON_COMMAND_VERBS and str(v).strip("'\"").lower() not in QUERY_STOP_WORDS
            ]
            if not clean_vals:
                continue
            col_base = col_l.split(".")[-1].strip('"`[] ')
            is_name_col = col_base in ("name", "patient_name", "doctor_name", "customer_name", "product_name", "first_name", "last_name", "full_name")
            if is_name_col:
                if len(clean_vals) > 1:
                    names_str = " or ".join(f"'{v}'" for v in clean_vals)
                    explanation = f"No {entity} found with the name {names_str}. Please check the spelling and try again."
                else:
                    explanation = f"No {entity} found with the name '{clean_vals[0]}'. Please check the spelling and try again."
                break
            else:
                col_lbl = col_base.replace("_", " ").strip()
                if len(clean_vals) > 1:
                    vals_str = " or ".join(f"'{v}'" for v in clean_vals)
                    explanation = f"Query executed successfully — no {entity_plural} found matching {col_lbl} {vals_str}."
                else:
                    explanation = f"Query executed successfully — no {entity_plural} found matching {col_lbl} '{clean_vals[0]}'."
                break

        # Check if a true name column was filtered via LIKE or = regex if not yet resolved
        if not explanation:
            name_col_pattern = r"(?:(?:LOWER\s*\(\s*)?([a-zA-Z0-9_\.]*name[a-zA-Z0-9_\.]*)(?:\s*\))?)\s*(?:LIKE|=)\s*['\"]%?([^%'\"]+)%?['\"]"
            name_matches = re.findall(name_col_pattern, where_clause, re.IGNORECASE)

            for col_name, val in name_matches:
                val_clean = val.strip()
                val_l = val_clean.lower()
                col_base = col_name.lower().split(".")[-1]
                if col_base in ("name", "patient_name", "doctor_name", "customer_name", "product_name", "first_name", "last_name", "full_name"):
                    if val_l not in COMMON_COMMAND_VERBS and val_l not in QUERY_STOP_WORDS:
                        specific_search_val = val_clean
                        is_name_search = True
                        break

            if is_name_search and specific_search_val:
                explanation = f"No {entity} found with the name '{specific_search_val}'. Please check the spelling and try again."

        # Date without year: strftime('%m', ...) BETWEEN '01' AND '02'
        if not explanation:
            m_range = re.search(r"strftime\s*\(\s*['\"]%m['\"]\s*,\s*[^)]+\)\s*BETWEEN\s*['\"](\d{2})['\"]\s*AND\s*['\"](\d{2})['\"]", where_clause, re.IGNORECASE)
            if m_range:
                m1, m2 = m_range.group(1), m_range.group(2)
                m1_name = MONTH_NAMES.get(m1, f"month {m1}")
                m2_name = MONTH_NAMES.get(m2, f"month {m2}")
                explanation = f"Query executed successfully — no {entity_plural} found with appointments between {m1_name} and {m2_name} (no year given, so all years were included)."

        # Date without year: strftime('%m', ...) = '03'
        if not explanation:
            m_single = re.search(r"strftime\s*\(\s*['\"]%m['\"]\s*,\s*[^)]+\)\s*=\s*['\"](\d{2})['\"]", where_clause, re.IGNORECASE)
            if m_single:
                m = m_single.group(1)
                m_name = MONTH_NAMES.get(m, f"month {m}")
                explanation = f"Query executed successfully — no {entity_plural} found for {m_name} (no year given, so all years were included)."

        # Explicit date range: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
        if not explanation:
            d_range = re.search(r"(?:BETWEEN\s*['\"](\d{4}-\d{2}-\d{2})['\"]\s*AND\s*['\"](\d{4}-\d{2}-\d{2})['\"])", where_clause, re.IGNORECASE)
            if d_range:
                d1, d2 = d_range.group(1), d_range.group(2)
                explanation = f"Query executed successfully — no {entity_plural} found between {d1} and {d2}."

        # Year filter: strftime('%Y', ...) = 'YYYY' or LIKE 'YYYY%'
        if not explanation:
            y_match = re.search(r"strftime\s*\(\s*['\"]%Y['\"]\s*,\s*[^)]+\)\s*=\s*['\"](\d{4})['\"]", where_clause, re.IGNORECASE)
            if not y_match:
                y_match = re.search(r"[a-zA-Z0-9_\.]+\s*LIKE\s*['\"](\d{4})%['\"]", where_clause, re.IGNORECASE)
            if not y_match:
                y_match = re.search(r"[a-zA-Z0-9_\.]+\s*=\s*['\"](\d{4})['\"]", where_clause, re.IGNORECASE)
            if y_match:
                year_val = y_match.group(1)
                explanation = f"Query executed successfully — no {entity_plural} found for year {year_val}."

        # Relative date: date('now', '-30 days')
        if not explanation:
            if "date('now'" in where_clause.lower() or 'date("now"' in where_clause.lower():
                if "-30 day" in where_clause.lower():
                    explanation = f"Query executed successfully — no {entity_plural} found in the last 30 days."
                else:
                    explanation = f"Query executed successfully — no {entity_plural} found matching recent date criteria."

        # Specific attribute filter in WHERE (e.g. diagnosis = 'XYZ' or status = 'ABC')
        if not explanation:
            lit_match = re.search(r"([a-zA-Z0-9_\.]+)\s*=\s*['\"]([^'\"]+)['\"]", where_clause)
            if lit_match:
                col, val = lit_match.group(1).split(".")[-1], lit_match.group(2)
                if val.lower() not in COMMON_COMMAND_VERBS:
                    explanation = f"Query executed successfully — no {entity_plural} found matching {col} '{val}'."

    if not explanation:
        # Generic criteria summary from question
        criteria = re.sub(
            r"^(?:list\s+of|show\s+me|find|get|give\s+me|give|display|search\s+for|what\s+are\s+the|which)\s+",
            "",
            question.strip(),
            flags=re.IGNORECASE,
        ).strip()
        if criteria.lower().startswith(entity_plural):
            remainder = criteria[len(entity_plural):].strip()
            if remainder:
                explanation = f"Query executed successfully — no {entity_plural} found {remainder}."
            else:
                explanation = f"Query executed successfully — no {entity_plural} found."
        elif criteria.lower().startswith(entity):
            remainder = criteria[len(entity):].strip()
            if remainder:
                explanation = f"Query executed successfully — no {entity} found {remainder}."
            else:
                explanation = f"Query executed successfully — no {entity} found."
        else:
            explanation = f"Query executed successfully — no {entity_plural} found matching '{criteria}'."


    # 5. Language constraints
    if detected_language == "thanglish":
        if not (explanation.startswith("Understood —") or explanation.startswith("Understood -")):
            explanation = f"Understood — {explanation}"
    elif detected_language == "tamil":
        explanation = f"வினவல் வெற்றிகரமாக செயல்படுத்தப்பட்டது — கொடுக்கப்பட்ட நிபந்தனைக்கு ஏற்ற தகவல்கள் எதுவும் கிடைக்கவில்லை."

    return explanation


