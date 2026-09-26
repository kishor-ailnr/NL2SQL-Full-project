import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
import google.generativeai as genai
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.meta_db import ConversationModel, QueryHistoryModel, get_db_session
from app.services.sql_generator import generate_sql, regenerate_sql, generate_zero_result_explanation
from app.services.sql_validator import validate_sql
from app.services.execution_engine import run_select
from app.services.session_store import get_session

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Rate Limiting — two-tier sliding window (in-memory)
# ---------------------------------------------------------------------------
# Tier 1 (per-session):  20 requests / minute per session_id
#   — prevents a single user from hammering Gemini via one session.
# Tier 2 (global):      100 requests / minute across ALL sessions combined
#   — prevents a client from creating many session IDs to bypass Tier 1
#     and exhausting the free Gemini quota.
# ---------------------------------------------------------------------------
# In-memory store: session_id -> list[float timestamps]
_QUERY_TIMESTAMPS: Dict[str, List[float]] = defaultdict(list)

RATE_LIMIT_PER_MINUTE = 20          # per session
GLOBAL_RATE_LIMIT_PER_MINUTE = 100  # across all sessions
WINDOW_SECONDS = 60.0

# Global sentinel key — never a valid UUID session_id
_GLOBAL_KEY = "__global__"


def generate_conversation_title(question: str) -> str:
    """Generate a clean 3-5 word title summarizing the user question instantly with zero latency."""
    words = question.strip().split()
    title = " ".join(words[:5]).capitalize()
    return title[:40]


def check_rate_limit(session_id: str) -> None:
    """Enforce two-tier in-memory rate limiting on /api/query.

    Tier 1 — Global:      100 requests / minute across ALL session IDs combined.
    Tier 2 — Per-session: 20 requests  / minute per individual session_id.

    Both tiers use a sliding 60-second window. The global check runs first so
    that a client creating many session IDs to bypass per-session limits is
    caught before the per-session bucket is even updated.
    """
    now = time.time()
    cutoff = now - WINDOW_SECONDS

    # Memory leak fix (UE-03): purge expired session keys entirely from _QUERY_TIMESTAMPS
    expired_sessions = [
        sid for sid, timestamps in _QUERY_TIMESTAMPS.items()
        if sid != _GLOBAL_KEY and (not timestamps or timestamps[-1] <= cutoff)
    ]
    for sid in expired_sessions:
        del _QUERY_TIMESTAMPS[sid]

    # --- Tier 1: Global limit ---
    global_timestamps = [t for t in _QUERY_TIMESTAMPS.get(_GLOBAL_KEY, []) if t > cutoff]
    if len(global_timestamps) >= GLOBAL_RATE_LIMIT_PER_MINUTE:
        retry_after = int(WINDOW_SECONDS - (now - global_timestamps[0])) + 1
        logger.warning(
            "Global rate limit exceeded (%d requests in 60s from all sessions). Retry after %ds",
            len(global_timestamps),
            retry_after,
        )
        raise HTTPException(
            status_code=429,
            detail="Server is under heavy load. Please wait a moment before trying again.",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    # --- Tier 2: Per-session limit ---
    session_timestamps = [t for t in _QUERY_TIMESTAMPS.get(session_id, []) if t > cutoff]
    if len(session_timestamps) >= RATE_LIMIT_PER_MINUTE:
        retry_after = int(WINDOW_SECONDS - (now - session_timestamps[0])) + 1
        logger.warning(
            "Per-session rate limit exceeded for session_id '%s' (%d requests in 60s). Retry after %ds",
            session_id,
            len(session_timestamps),
            retry_after,
        )
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Maximum 20 queries per minute per session. Please wait a moment before trying again.",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    # Record this request in both buckets
    global_timestamps.append(now)
    _QUERY_TIMESTAMPS[_GLOBAL_KEY] = global_timestamps

    session_timestamps.append(now)
    _QUERY_TIMESTAMPS[session_id] = session_timestamps



def reset_rate_limits() -> None:
    """Reset rate limiter state (used for testing)."""
    _QUERY_TIMESTAMPS.clear()


# In-memory staged write queries: query_id -> dict
_PENDING_WRITES: Dict[str, Dict[str, Any]] = {}


class QueryRequest(BaseModel):
    session_id: str = Field(..., description="ID of the active database session")
    conversation_id: Optional[str] = Field(None, description="UUID of the active conversation")
    text: str = Field(..., description="Natural language user question")
    language: str = Field("auto", description="Language code, default 'auto'")


class QueryResponse(BaseModel):
    query_id: Union[str, int]
    sql: Optional[str] = None
    explanation: Optional[str] = None
    confidence: float = 1.0
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    needs_confirmation: bool = False
    confirmation_question: Optional[str] = None
    suggested_value: Optional[str] = None
    query_type: str = "select"
    result: List[Any] = []
    chart_type: str = "none"
    interpreted_text: Optional[str] = None
    detected_language: Optional[str] = None
    self_corrected: bool = False
    correction_attempts: int = 0
    data_available: Optional[bool] = True
    unavailable_message: Optional[str] = None
    corrected_terms: Optional[List[Dict[str, Any]]] = []


class ConfirmWriteRequest(BaseModel):
    session_id: str = Field(..., description="Active database session ID")
    query_id: str = Field(..., description="ID of the staged write query")
    confirmed: bool = Field(..., description="True to execute the modification, False to cancel")


class ConfirmWriteResponse(BaseModel):
    status: str = Field(..., description="'executed', 'cancelled', or 'error'")
    rows_affected: int = Field(0, description="Number of database rows modified")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    result: List[Dict[str, Any]] = Field(default_factory=list, description="Rows returned if query included a SELECT statement")
    chart_type: str = Field("none", description="Suggested visualization type for returned rows")
    notice: Optional[str] = Field(None, description="Informational notice, e.g. duplicate skipped")






@router.post("/query", response_model=QueryResponse)
def handle_query(
    payload: QueryRequest,
    db: Session = Depends(get_db_session),
):
    """Translate natural language to SQL, validate it, execute it, and record history."""
    # 0. Enforce Rate Limiting (20 queries / min per session_id)
    check_rate_limit(payload.session_id)

    session = get_session(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="Active session not found. Please connect to a database first.",
        )

    # Ensure conversation exists; if omitted or not found, auto-create under this session
    target_conv_id = payload.conversation_id
    if target_conv_id:
        conv = db.query(ConversationModel).filter(ConversationModel.id == target_conv_id).first()
        if not conv:
            conv = ConversationModel(
                id=target_conv_id,
                session_id=payload.session_id,
                title="New Chat",
                created_at=datetime.utcnow(),
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
    else:
        conv = ConversationModel(
            id=str(uuid.uuid4()),
            session_id=payload.session_id,
            title="New Chat",
            created_at=datetime.utcnow(),
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    # Auto-generate title from the first question if currently default "New Chat"
    if conv.title in ("New Chat", "", None):
        try:
            conv.title = generate_conversation_title(payload.text)
            db.commit()
        except Exception as title_err:
            logger.warning("Could not auto-generate conversation title: %s", title_err)

    # Conversational Context for follow-up query awareness
    conv_context = None
    try:
        last_history = (
            db.query(QueryHistoryModel)
            .filter(QueryHistoryModel.conversation_id == conv.id)
            .order_by(QueryHistoryModel.created_at.desc())
            .first()
        )
        if last_history:
            prev_conf = None
            if last_history.query_type == "confirmation" and last_history.corrections_json:
                try:
                    cdata = json.loads(last_history.corrections_json)
                    if cdata.get("needs_confirmation"):
                        prev_conf = {
                            "suggested_value": cdata.get("suggested_value"),
                            "literal_value": cdata.get("literal_value"),
                            "confirmation_question": last_history.explanation,
                        }
                except Exception as c_err:
                    logger.warning("Could not parse previous confirmation data: %s", c_err)

            prev_sql = last_history.generated_sql if (last_history.generated_sql and not last_history.generated_sql.startswith("--")) else None
            conv_context = {
                "previous_question": last_history.nl_query,
                "previous_sql": prev_sql,
                "previous_confirmation": prev_conf,
            }
    except Exception as ctx_err:
        logger.warning("Could not fetch conversation context: %s", ctx_err)

    # 1. Generate SQL using Gemini (with clarification, follow-ups, and write intent detection)
    try:
        gen_data = generate_sql(
            payload.session_id,
            payload.text,
            language=payload.language,
            conversation_context=conv_context,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Error generating SQL for session '%s' and question '%s': %s",
            payload.session_id,
            payload.text,
            exc,
            exc_info=True,
        )
        err_msg = str(exc)
        if "429" in err_msg or "quota" in err_msg.lower() or "toomanyrequests" in type(exc).__name__.lower():
            raise HTTPException(
                status_code=429,
                detail="AI service rate limit or quota exceeded. Please wait a moment and try again.",
            )
        logger.warning(
            "Fallback clarification triggered after SQL generation error for session '%s': %s",
            payload.session_id,
            exc,
        )
        gen_data = {
            "data_available": True,
            "unavailable_message": None,
            "corrected_terms": [],
            "needs_clarification": True,
            "clarification_question": "I could not generate a SQL query for this question. Could you please clarify your request with more specific criteria or table names?",
            "interpreted_text": payload.text,
            "sql": None,
            "explanation": None,
            "confidence": 0.2,
            "detected_language": "english",
        }

    interpreted_text = gen_data.get("interpreted_text") or payload.text
    detected_lang = gen_data.get("detected_language")
    data_available = bool(gen_data.get("data_available", True))
    unavailable_msg = gen_data.get("unavailable_message")
    corrected_terms = gen_data.get("corrected_terms") or []

    # Handle data unavailable in connected database schema
    if not data_available:
        msg_text = unavailable_msg or "This information is not tracked in the connected database schema."
        query_record = QueryHistoryModel(
            session_id=payload.session_id,
            conversation_id=conv.id,
            nl_query=payload.text,
            generated_sql="-- Data unavailable in schema",
            explanation=msg_text,
            result_json="[]",
            chart_type="none",
            confidence=0.85,
            query_type="unavailable",
            self_corrected=0,
            correction_attempts=0,
            created_at=datetime.utcnow(),
        )
        db.add(query_record)
        db.commit()
        db.refresh(query_record)

        return QueryResponse(
            query_id=str(query_record.id),
            sql=None,
            explanation=msg_text,
            confidence=0.85,
            needs_clarification=False,
            clarification_question=None,
            query_type="unavailable",
            result=[],
            chart_type="none",
            interpreted_text=interpreted_text,
            detected_language=detected_lang,
            self_corrected=False,
            correction_attempts=0,
            data_available=False,
            unavailable_message=msg_text,
            corrected_terms=corrected_terms,
        )

    # Handle clarification needed before validation or execution
    if gen_data.get("needs_clarification", False):
        clarification_q = gen_data.get("clarification_question") or "Could you please clarify your request?"
        confidence = float(gen_data.get("confidence", 0.3))

        query_record = QueryHistoryModel(
            session_id=payload.session_id,
            conversation_id=conv.id,
            nl_query=payload.text,
            generated_sql="-- Needs clarification: " + clarification_q,
            explanation=clarification_q,
            result_json="[]",
            chart_type="none",
            confidence=confidence,
            query_type="clarification",
            created_at=datetime.utcnow(),
        )
        db.add(query_record)
        db.commit()
        db.refresh(query_record)

        return QueryResponse(
            query_id=str(query_record.id),
            sql=None,
            explanation=None,
            confidence=confidence,
            needs_clarification=True,
            clarification_question=clarification_q,
            needs_confirmation=False,
            confirmation_question=None,
            suggested_value=None,
            query_type="select",
            result=[],
            chart_type="none",
            interpreted_text=interpreted_text,
            detected_language=detected_lang,
            data_available=True,
            unavailable_message=None,
            corrected_terms=corrected_terms,
        )

    # Handle confirmation flow for near-miss values before execution
    if gen_data.get("needs_confirmation", False):
        sugg_val = gen_data.get("suggested_value")
        conf_q = gen_data.get("confirmation_question") or f"Did you mean '{sugg_val}'?"
        confidence = float(gen_data.get("confidence", 0.85))

        query_record = QueryHistoryModel(
            session_id=payload.session_id,
            conversation_id=conv.id,
            nl_query=payload.text,
            generated_sql=f"-- Needs confirmation: {sugg_val}" if sugg_val else "-- Needs confirmation",
            explanation=conf_q,
            result_json="[]",
            chart_type="none",
            confidence=confidence,
            query_type="confirmation",
            corrections_json=json.dumps({
                "needs_confirmation": True,
                "suggested_value": sugg_val,
                "literal_value": gen_data.get("literal_value") or payload.text,
                "confirmation_question": conf_q,
            }),
            created_at=datetime.utcnow(),
        )
        db.add(query_record)
        db.commit()
        db.refresh(query_record)

        return QueryResponse(
            query_id=str(query_record.id),
            sql=None,
            explanation=None,
            confidence=confidence,
            needs_clarification=False,
            clarification_question=None,
            needs_confirmation=True,
            confirmation_question=conf_q,
            suggested_value=sugg_val,
            query_type="select",
            result=[],
            chart_type="none",
            interpreted_text=interpreted_text,
            detected_language=detected_lang,
            data_available=True,
            unavailable_message=None,
            corrected_terms=corrected_terms,
        )


    current_sql = gen_data.get("sql") or ""
    current_explanation = gen_data.get("explanation", "")
    current_confidence = float(gen_data.get("confidence", 0.9))
    query_type = gen_data.get("query_type", "select")
    upper_sql = current_sql.strip().upper()

    # Guard: Empty SQL or forbidden DDL statements (DROP, ALTER, TRUNCATE, CREATE)
    if not current_sql or any(upper_sql.startswith(k) for k in ("DROP", "ALTER", "TRUNCATE", "CREATE")):
        err_msg = current_explanation or "Schema modification operations (such as DROP or ALTER TABLE) are prohibited."
        query_record = QueryHistoryModel(
            session_id=payload.session_id,
            conversation_id=conv.id,
            nl_query=payload.text,
            generated_sql=current_sql or "",
            explanation=err_msg,
            result_json="[]",
            chart_type="none",
            confidence=0.0,
            query_type="select",
            created_at=datetime.utcnow(),
        )
        db.add(query_record)
        db.commit()
        db.refresh(query_record)
        return QueryResponse(
            query_id=str(query_record.id),
            sql=None,
            explanation=err_msg,
            confidence=0.0,
            needs_clarification=False,
            clarification_question=None,
            query_type="select",
            result=[],
            chart_type="none",
            interpreted_text=interpreted_text,
            detected_language=detected_lang,
            data_available=True,
            unavailable_message=None,
            corrected_terms=corrected_terms,
        )

    # Controlled Write Operations (INSERT, UPDATE, DELETE) -> stage for user confirmation
    is_write = query_type == "write" or any(upper_sql.startswith(k) for k in ("INSERT", "UPDATE", "DELETE"))

    if is_write:
        validation = validate_sql(current_sql, allow_write=True)
        if not validation.get("valid"):
            err_msg = validation.get("message", "Invalid SQL write operation.")
            query_record = QueryHistoryModel(
                session_id=payload.session_id,
                conversation_id=conv.id,
                nl_query=payload.text,
                generated_sql=current_sql,
                explanation=err_msg,
                result_json="[]",
                chart_type="none",
                confidence=0.0,
                query_type="write",
                created_at=datetime.utcnow(),
            )
            db.add(query_record)
            db.commit()
            db.refresh(query_record)
            return QueryResponse(
                query_id=str(query_record.id),
                sql=current_sql,
                explanation=err_msg,
                confidence=0.0,
                needs_clarification=False,
                clarification_question=None,
                query_type="write",
                result=[],
                chart_type="none",
                interpreted_text=interpreted_text,
                detected_language=detected_lang,
                data_available=True,
                unavailable_message=None,
                corrected_terms=corrected_terms,
            )

        # Valid write operation: stage for user confirmation
        query_record = QueryHistoryModel(
            session_id=payload.session_id,
            conversation_id=conv.id,
            nl_query=payload.text,
            generated_sql=current_sql,
            explanation=current_explanation,
            result_json="[]",
            chart_type="none",
            confidence=current_confidence,
            query_type="write",
            created_at=datetime.utcnow(),
        )
        db.add(query_record)
        db.commit()
        db.refresh(query_record)

        qid_str = str(query_record.id)
        _PENDING_WRITES[qid_str] = {
            "session_id": payload.session_id,
            "conversation_id": conv.id,
            "sql": current_sql,
            "explanation": current_explanation,
            "created_at": time.time(),
        }

        return QueryResponse(
            query_id=qid_str,
            sql=current_sql,
            explanation=current_explanation,
            confidence=current_confidence,
            needs_clarification=False,
            clarification_question=None,
            query_type="write",
            result=[],
            chart_type="none",
            interpreted_text=interpreted_text,
            detected_language=detected_lang,
            data_available=True,
            unavailable_message=None,
            corrected_terms=corrected_terms,
        )

    # Self-Correction Retry Loop for Read (SELECT) queries: up to 2 retries (original attempt + 2 retries = 3 attempts max)
    MAX_RETRIES = 2
    attempt = 0
    corrections_history: List[Dict[str, Any]] = []
    self_corrected = False
    validation: Optional[Dict[str, Any]] = None
    exec_result: Any = None
    friendly_message: str = ""

    while attempt <= MAX_RETRIES:
        # Step A: Validate SQL syntax and safety via sqlglot
        validation = validate_sql(current_sql, allow_write=False)
        if not validation.get("valid", False):
            error_msg = validation.get("message", "Invalid SQL syntax.")
            logger.warning(
                "[Self-Correction] Attempt %d: SQL validation failed for session '%s'. SQL: '%s' | Error: '%s'",
                attempt + 1,
                payload.session_id,
                current_sql,
                error_msg,
            )
            if attempt < MAX_RETRIES:
                attempt += 1
                try:
                    regen_data = regenerate_sql(
                        session_id=payload.session_id,
                        original_question=payload.text,
                        failed_sql=current_sql,
                        error_message=error_msg,
                    )
                    new_sql = regen_data.get("sql", "")
                    logger.info(
                        "[Self-Correction] Retry %d generated corrected SQL: '%s'",
                        attempt,
                        new_sql,
                    )
                    corrections_history.append({
                        "attempt": attempt,
                        "failed_sql": current_sql,
                        "error": error_msg,
                        "corrected_sql": new_sql,
                    })
                    current_sql = new_sql
                    current_explanation = regen_data.get("explanation", current_explanation)
                    current_confidence = float(regen_data.get("confidence", 0.85))
                    self_corrected = True
                    continue
                except Exception as r_exc:
                    logger.error("[Self-Correction] regenerate_sql call failed: %s", r_exc)
                    friendly_message = error_msg
                    break
            else:
                friendly_message = error_msg
                break

        # Step B: Execute SQL against SQLite database
        exec_result = run_select(payload.session_id, current_sql)
        if isinstance(exec_result, dict) and "error" in exec_result:
            error_msg = f"Database query execution failed: {exec_result['error']}"
            logger.warning(
                "[Self-Correction] Attempt %d: Database execution failed for session '%s'. SQL: '%s' | Error: '%s'",
                attempt + 1,
                payload.session_id,
                current_sql,
                error_msg,
            )
            if attempt < MAX_RETRIES:
                attempt += 1
                try:
                    regen_data = regenerate_sql(
                        session_id=payload.session_id,
                        original_question=payload.text,
                        failed_sql=current_sql,
                        error_message=error_msg,
                    )
                    new_sql = regen_data.get("sql", "")
                    logger.info(
                        "[Self-Correction] Retry %d generated corrected SQL: '%s'",
                        attempt,
                        new_sql,
                    )
                    corrections_history.append({
                        "attempt": attempt,
                        "failed_sql": current_sql,
                        "error": error_msg,
                        "corrected_sql": new_sql,
                    })
                    current_sql = new_sql
                    current_explanation = regen_data.get("explanation", current_explanation)
                    current_confidence = float(regen_data.get("confidence", 0.85))
                    self_corrected = True
                    continue
                except Exception as r_exc:
                    logger.error("[Self-Correction] regenerate_sql call failed: %s", r_exc)
                    friendly_message = error_msg
                    break
            else:
                friendly_message = error_msg
                break

        # Both validation and execution succeeded!
        break

    # Determine whether the final query succeeded or failed
    is_failed = (
        (validation is not None and not validation.get("valid", False))
        or (isinstance(exec_result, dict) and "error" in exec_result)
    )

    if is_failed:
        # Exhausted all retries without success: record failed query and return friendly error
        query_record = QueryHistoryModel(
            session_id=payload.session_id,
            conversation_id=conv.id,
            nl_query=payload.text,
            generated_sql=current_sql,
            explanation=friendly_message,
            result_json="[]",
            chart_type="none",
            confidence=0.0,
            query_type="select",
            self_corrected=0,
            correction_attempts=attempt,
            corrections_json=json.dumps(corrections_history) if corrections_history else None,
            created_at=datetime.utcnow(),
        )
        db.add(query_record)
        db.commit()
        db.refresh(query_record)

        return QueryResponse(
            query_id=str(query_record.id),
            sql=current_sql,
            explanation=friendly_message,
            confidence=0.0,
            needs_clarification=False,
            clarification_question=None,
            query_type="select",
            result=[],
            chart_type="none",
            interpreted_text=interpreted_text,
            detected_language=detected_lang,
            self_corrected=False,
            correction_attempts=attempt,
            data_available=True,
            unavailable_message=None,
            corrected_terms=corrected_terms,
        )

    # Success (either on first attempt or after self-correction)
    # Bug 1 Fix: Zero-row reasoning for successful SELECT queries
    if isinstance(exec_result, list) and len(exec_result) == 0:
        current_explanation = generate_zero_result_explanation(
            question=payload.text,
            sql=current_sql,
            original_explanation=current_explanation,
            detected_language=detected_lang,
        )

    query_record = QueryHistoryModel(
        session_id=payload.session_id,
        conversation_id=conv.id,
        nl_query=payload.text,
        generated_sql=current_sql,
        explanation=current_explanation,
        result_json=json.dumps(exec_result) if exec_result else "[]",
        chart_type="none",
        confidence=current_confidence,
        query_type="select",
        self_corrected=1 if self_corrected else 0,
        correction_attempts=attempt,
        corrections_json=json.dumps(corrections_history) if corrections_history else None,
        created_at=datetime.utcnow(),
    )
    db.add(query_record)
    db.commit()
    db.refresh(query_record)

    return QueryResponse(
        query_id=str(query_record.id),
        sql=current_sql,
        explanation=current_explanation,
        confidence=current_confidence,
        needs_clarification=False,
        clarification_question=None,
        query_type="select",
        result=exec_result or [],
        chart_type="none",
        interpreted_text=interpreted_text,
        detected_language=detected_lang,
        self_corrected=self_corrected,
        correction_attempts=attempt,
        data_available=True,
        unavailable_message=None,
        corrected_terms=corrected_terms,
    )


@router.post("/confirm-write", response_model=ConfirmWriteResponse)
def confirm_write(
    payload: ConfirmWriteRequest,
    db: Session = Depends(get_db_session),
):
    """Confirm or cancel execution of a staged write SQL operation."""
    # 0. Enforce Rate Limiting (same sliding window as /api/query)
    check_rate_limit(payload.session_id)

    query_id = str(payload.query_id)
    pending = _PENDING_WRITES.get(query_id)

    # 1. Validate session ownership from in-memory staged queries
    if pending:
        if pending.get("session_id") != payload.session_id:
            logger.warning(
                "Unauthorized confirm-write attempt: session '%s' tried to confirm query '%s' belonging to session '%s'",
                payload.session_id,
                query_id,
                pending.get("session_id"),
            )
            raise HTTPException(
                status_code=403,
                detail="Forbidden: This pending write query belongs to a different session.",
            )

    if not pending:
        # Fallback: Query by explicit integer query_id in database history
        int_qid = int(query_id) if query_id.isdigit() else None
        hist = db.query(QueryHistoryModel).filter(QueryHistoryModel.id == int_qid).first() if int_qid is not None else None

        if hist:
            # Enforce session ownership on database history record
            if hist.session_id != payload.session_id:
                logger.warning(
                    "Unauthorized confirm-write attempt: session '%s' tried to confirm query '%s' belonging to session '%s'",
                    payload.session_id,
                    query_id,
                    hist.session_id,
                )
                raise HTTPException(
                    status_code=403,
                    detail="Forbidden: This pending write query belongs to a different session.",
                )

            # Check if this write query was already executed (prevents double execution)
            if hist.result_json and hist.result_json != "[]":
                return ConfirmWriteResponse(
                    status="executed",
                    rows_affected=0,
                    notice="This write query was already confirmed and executed.",
                )

            if hist.query_type == "write" and hist.generated_sql and not hist.generated_sql.startswith("--"):
                pending = {
                    "session_id": hist.session_id,
                    "conversation_id": hist.conversation_id,
                    "sql": hist.generated_sql,
                    "explanation": hist.explanation or "",
                    "created_at": time.time(),
                }
                query_id = str(hist.id)

    if not pending:
        raise HTTPException(
            status_code=404,
            detail="Pending write query not found or already processed.",
        )

    # Atomically pop from in-memory staged writes to guarantee single-use execution
    _PENDING_WRITES.pop(query_id, None)

    if not payload.confirmed:
        return ConfirmWriteResponse(
            status="cancelled",
            rows_affected=0,
        )

    # Confirmed execution: retrieve SQL server-side from staged pending dict
    from app.services.execution_engine import run_write
    from app.services.sql_generator import clear_query_cache

    sql_to_run = pending["sql"]
    res = run_write(payload.session_id, sql_to_run)

    if not res.get("success", False):
        err_msg = res.get("error", "Failed to execute database write operation.")
        return ConfirmWriteResponse(
            status="error",
            rows_affected=0,
            error=err_msg,
        )

    rows_affected = res.get("rows_affected", 0)
    result_rows = res.get("result", [])
    notice = res.get("notice")

    # Invalidate query cache because data changed
    clear_query_cache(payload.session_id)

    # Automatically advise visualization chart type if SELECT rows were returned
    chart_type = "none"
    if result_rows:
        try:
            from app.services.chart_advisor import advise_chart_type
            chart_type = advise_chart_type(result_rows, pending["sql"])
        except Exception as chart_err:
            logger.warning("Chart advisor error on confirm_write: %s", chart_err)
            chart_type = "table"

    # Update query history with execution result
    hist = db.query(QueryHistoryModel).filter(QueryHistoryModel.id == query_id).first()
    if hist:
        hist.result_json = json.dumps(result_rows if result_rows else [{"status": "success", "rows_affected": rows_affected}])
        hist.chart_type = chart_type
        db.commit()

    return ConfirmWriteResponse(
        status="executed",
        rows_affected=rows_affected,
        result=result_rows,
        chart_type=chart_type,
        notice=notice,
    )

