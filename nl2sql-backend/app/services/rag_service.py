"""Schema-aware retrieval (RAG) using SentenceTransformers and FAISS.

Indexes database tables by their schema metadata (table name, column names, types,
and sample values) into a FAISS vector index per session. During SQL generation,
queries this index to retrieve only the top relevant tables for large schemas,
preventing token bloat while keeping small schemas (<= 4 tables) fully intact.
"""

import logging
from typing import Any, Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

# Lazy singleton model holder
_EMBEDDING_MODEL = None
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# In-memory store: session_id -> {
#     "index": faiss.IndexFlatIP,
#     "table_names": List[str],
#     "table_summaries": Dict[str, str],
#     "dimension": int,
# }
_SESSION_RAG_STORE: Dict[str, Dict[str, Any]] = {}


def get_embedding_model():
    """Lazily load SentenceTransformer model."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Initializing SentenceTransformer('%s')...", EMBEDDING_MODEL_NAME)
            _EMBEDDING_MODEL = SentenceTransformer(EMBEDDING_MODEL_NAME)
            logger.info("SentenceTransformer model loaded successfully.")
        except Exception as e:
            logger.error("Failed to load SentenceTransformer model: %s", e)
            raise
    return _EMBEDDING_MODEL


def build_table_summary(
    table_name: str,
    columns: Any,
    sample_values_map: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a rich, semantically meaningful text representation of a table.

    Includes the table name, its columns, data types, and representative sample values
    to enable accurate semantic retrieval matching user queries.
    """
    col_descs = []
    columns_list = columns if isinstance(columns, (list, tuple)) else []
    for c in columns_list:
        if isinstance(c, dict):
            col_name = c.get("name", "")
            col_type = c.get("type", "")
            samples = c.get("sample_values")
            if not samples and sample_values_map:
                samples = sample_values_map.get(col_name)
            samples = samples or []
        else:
            col_name = str(c)
            col_type = ""
            samples = []

        # Take up to 3 distinct non-empty sample values
        sample_strs = [str(s) for s in samples[:3] if s is not None and str(s).strip()]
        if sample_strs:
            sample_part = ", ".join(sample_strs)
            if col_type:
                col_descs.append(f"{col_name} ({col_type}, samples: {sample_part})")
            else:
                col_descs.append(f"{col_name} (samples: {sample_part})")
        else:
            if col_type:
                col_descs.append(f"{col_name} ({col_type})")
            else:
                col_descs.append(col_name)

    cols_text = "; ".join(col_descs) if col_descs else "no columns"
    summary = f"Table '{table_name}' with columns: {cols_text}."
    return summary


def build_schema_index(
    session_id: str,
    tables: Any,
    schema: Optional[Dict[str, Any]] = None,
    sample_values: Optional[Dict[str, Dict[str, List[Any]]]] = None,
) -> None:
    """Generate embeddings for table summaries and store them in a FAISS IndexFlatIP index.

    Supports both signatures:
      build_schema_index(session_id, tables, schema, sample_values)
      build_schema_index(session_id, schema)  # where schema is Dict[str, list]
    """
    if schema is None and isinstance(tables, dict):
        schema = tables
        table_list_input = list(schema.keys())
    else:
        table_list_input = list(tables) if tables else []
        schema = schema or {}

    if not table_list_input:
        logger.warning("No tables provided to build_schema_index for session '%s'", session_id)
        return

    # Skip embedding generation and model loading for small schemas (<= 4 tables).
    # Since retrieve_relevant_tables returns all tables directly for schemas <= 4,
    # we avoid loading SentenceTransformer and PyTorch into memory during typical demo sessions.
    if len(table_list_input) <= 4:
        _SESSION_RAG_STORE[session_id] = {
            "index": None,
            "table_names": table_list_input,
            "table_summaries": {},
            "dimension": 0,
        }
        logger.info(
            "Session '%s' has %d tables (<= 4). Skipping RAG embedding indexing to preserve memory.",
            session_id,
            len(table_list_input),
        )
        return

    try:
        import faiss

        model = get_embedding_model()
        summaries: List[str] = []
        table_list: List[str] = []

        for tbl in table_list_input:
            cols = schema.get(tbl, [])
            tbl_samples = (sample_values or {}).get(tbl, {})
            summary = build_table_summary(tbl, cols, tbl_samples)
            summaries.append(summary)
            table_list.append(tbl)

        # Generate normalized embeddings for cosine similarity
        raw_embeddings = model.encode(summaries, convert_to_numpy=True, normalize_embeddings=True)
        embeddings = np.ascontiguousarray(raw_embeddings, dtype=np.float32)

        dimension = embeddings.shape[1]
        index = faiss.IndexFlatIP(dimension)
        index.add(embeddings)

        _SESSION_RAG_STORE[session_id] = {
            "index": index,
            "table_names": table_list,
            "table_summaries": dict(zip(table_list, summaries)),
            "dimension": dimension,
        }
        logger.info(
            "Successfully built FAISS RAG index for session '%s' with %d tables (dimension=%d).",
            session_id,
            len(table_list),
            dimension,
        )
    except Exception as exc:
        logger.error(
            "Failed to build FAISS RAG index for session '%s': %s",
            session_id,
            exc,
            exc_info=True,
        )


def retrieve_relevant_tables(
    session_id: str,
    query_text: str,
    top_k: int = 4,
) -> List[str]:
    """Retrieve the top_k most relevant tables for a user query.

    Rules:
    - If total tables <= 4, returns all tables immediately to avoid over-filtering
      on small schemas (like hospital or ecommerce demo databases).
    - If total tables > 4, calculates semantic cosine similarity against the FAISS index
      and returns top_k most relevant table names in order of relevance.
    """
    rag_data = _SESSION_RAG_STORE.get(session_id)

    # Lazily build index from session store if not yet in memory
    if not rag_data:
        from app.services.session_store import get_session
        session = get_session(session_id)
        if session:
            tables = session.get("tables", [])
            schema = session.get("schema", {})
            sample_values = session.get("sample_values", {})
            if tables and schema:
                build_schema_index(session_id, tables, schema, sample_values)
                rag_data = _SESSION_RAG_STORE.get(session_id)

    if not rag_data:
        # Fallback to session tables if index could not be built
        from app.services.session_store import get_session
        session = get_session(session_id)
        return list(session.get("tables", [])) if session else []

    table_names = rag_data["table_names"]
    total_tables = len(table_names)

    # If small schema (<= 4 tables), return all tables to prevent over-filtering
    if total_tables <= 4:
        return list(table_names)

    try:
        model = get_embedding_model()
        raw_query_vec = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)
        query_vec = np.ascontiguousarray(raw_query_vec, dtype=np.float32)

        k = min(top_k, total_tables)
        distances, indices = rag_data["index"].search(query_vec, k)

        retrieved: List[str] = []
        for idx in indices[0]:
            if 0 <= idx < total_tables:
                retrieved.append(table_names[idx])

        logger.info(
            "RAG retrieved %d tables for session '%s' query '%s': %s (scores: %s)",
            len(retrieved),
            session_id,
            query_text,
            retrieved,
            distances[0].tolist() if len(distances) > 0 else [],
        )
        return retrieved
    except Exception as exc:
        logger.error(
            "Error during RAG retrieval for session '%s': %s. Falling back to all tables.",
            session_id,
            exc,
        )
        return list(table_names)


def remove_schema_index(session_id: str) -> None:
    """Remove session FAISS index from in-memory cache."""
    _SESSION_RAG_STORE.pop(session_id, None)


