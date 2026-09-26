import json
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.meta_db import ConversationModel, QueryHistoryModel, get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateConversationRequest(BaseModel):
    session_id: str = Field(..., description="ID of the connected database session")


class CreateConversationResponse(BaseModel):
    conversation_id: str
    created_at: str


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    created_at: str


class ListConversationsResponse(BaseModel):
    conversations: List[ConversationSummary]


class MessageDetail(BaseModel):
    nl_query: str
    sql: Optional[str] = None
    explanation: Optional[str] = None
    result: List[Any] = []
    chart_type: str = "none"
    timestamp: str
    query_type: Optional[str] = "select"
    data_available: Optional[bool] = True
    unavailable_message: Optional[str] = None
    corrected_terms: Optional[List[Dict[str, Any]]] = []
    needs_confirmation: Optional[bool] = False
    confirmation_question: Optional[str] = None
    suggested_value: Optional[str] = None
    needs_clarification: Optional[bool] = False
    clarification_question: Optional[str] = None


class ConversationMessagesResponse(BaseModel):
    messages: List[MessageDetail]


@router.post("/conversations/new", response_model=CreateConversationResponse)
def create_conversation(
    payload: CreateConversationRequest,
    db: Session = Depends(get_db_session),
):
    """Create a new empty conversation under the given database session."""
    session_id = payload.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")

    conv_id = str(uuid.uuid4())
    new_conv = ConversationModel(
        id=conv_id,
        session_id=session_id,
        title="New Chat",
        created_at=datetime.utcnow(),
    )
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)

    logger.info("Created new conversation '%s' for session '%s'", conv_id, session_id)
    return CreateConversationResponse(
        conversation_id=new_conv.id,
        created_at=new_conv.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


@router.get("/conversations", response_model=ListConversationsResponse)
def list_conversations(
    session_id: str = Query(..., description="Filter conversations by session_id"),
    db: Session = Depends(get_db_session),
):
    """List all conversations for a session, ordered most recent first."""
    convs = (
        db.query(ConversationModel)
        .filter(ConversationModel.session_id == session_id)
        .order_by(ConversationModel.created_at.desc())
        .all()
    )

    return ListConversationsResponse(
        conversations=[
            ConversationSummary(
                conversation_id=c.id,
                title=c.title or "New Chat",
                created_at=c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else "",
            )
            for c in convs
        ]
    )


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def get_conversation_messages(
    conversation_id: str,
    db: Session = Depends(get_db_session),
):
    """Retrieve all messages for a conversation in chronological order."""
    conv = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    records = (
        db.query(QueryHistoryModel)
        .filter(QueryHistoryModel.conversation_id == conversation_id)
        .order_by(QueryHistoryModel.created_at.asc(), QueryHistoryModel.id.asc())
        .all()
    )

    messages = []
    for r in records:
        parsed_result = []
        if r.result_json:
            try:
                parsed_result = json.loads(r.result_json)
                if not isinstance(parsed_result, list):
                    parsed_result = [parsed_result]
            except Exception:
                parsed_result = []

        is_unavailable = r.query_type == "unavailable" or (r.generated_sql and r.generated_sql.startswith("-- Data unavailable"))
        is_conf = r.query_type == "confirmation" or (r.generated_sql and r.generated_sql.startswith("-- Needs confirmation"))
        is_clarif = not is_conf and (r.query_type == "clarification" or (r.generated_sql and r.generated_sql.startswith("-- Needs clarification:")))
        sql_val = None if (is_clarif or is_unavailable or is_conf) else r.generated_sql
        explanation_val = r.explanation
        sugg_val = None
        conf_q = None
        if is_conf and r.corrections_json:
            try:
                cdata = json.loads(r.corrections_json)
                sugg_val = cdata.get("suggested_value")
                conf_q = cdata.get("confirmation_question") or explanation_val
            except Exception:
                pass
        if is_conf and not conf_q:
            conf_q = explanation_val
        if is_clarif and not explanation_val and r.generated_sql:
            explanation_val = r.generated_sql.replace("-- Needs clarification: ", "")

        messages.append(
            MessageDetail(
                nl_query=r.nl_query,
                sql=sql_val,
                explanation=explanation_val,
                result=parsed_result,
                chart_type=r.chart_type or "none",
                timestamp=r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
                query_type=r.query_type or ("unavailable" if is_unavailable else ("confirmation" if is_conf else ("clarification" if is_clarif else "select"))),
                data_available=not is_unavailable,
                unavailable_message=explanation_val if is_unavailable else None,
                corrected_terms=[],
                needs_confirmation=is_conf,
                confirmation_question=conf_q,
                suggested_value=sugg_val,
                needs_clarification=is_clarif,
                clarification_question=explanation_val if is_clarif else None,
            )
        )

    return ConversationMessagesResponse(messages=messages)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db_session),
):
    """Delete a conversation and its associated query_history records (cascade delete)."""
    conv = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conv:
        # Cascade delete associated query history records
        db.query(QueryHistoryModel).filter(QueryHistoryModel.conversation_id == conversation_id).delete()
        db.delete(conv)
        db.commit()
        logger.info("Deleted conversation '%s' and its associated history rows", conversation_id)

    return {"status": "deleted"}
