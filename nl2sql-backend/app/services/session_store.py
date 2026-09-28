"""In-memory session store for connected database metadata and schema."""

from typing import Any, Dict, Optional

# Stores active sessions: session_id -> session_info_dict
SESSION_STORE: Dict[str, Dict[str, Any]] = {}


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve session data by session_id, falling back to restoring demo sessions from meta.db if needed."""
    session = SESSION_STORE.get(session_id)
    if session:
        return session

    # Attempt to restore demo session from metadata database (e.g. after server reload)
    try:
        from app.models.meta_db import SessionLocal, SessionModel
        from app.config import DATA_DIR

        db = SessionLocal()
        record = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        db.close()

        if record and record.db_type.startswith("demo_"):
            demo_name = record.db_type.replace("demo_", "")
            from app.routers.connect_db import get_demo_schema
            cached = get_demo_schema(demo_name)
            if cached:
                restored = {
                    "db_type": "demo",
                    "demo_name": demo_name,
                    "db_path": cached["db_path"],
                    "database_url": cached["database_url"],
                    "tables": cached["tables"],
                    "schema": cached["schema"],
                    "sample_values": cached.get("sample_values", {}),
                }
                SESSION_STORE[session_id] = restored
                try:
                    from app.database.manager import DatabaseConnectionManager
                    from app.database.sqlite_adapter import SQLiteAdapter
                    demo_adapter = SQLiteAdapter(database_url=cached["database_url"], db_path=cached["db_path"])
                    DatabaseConnectionManager.register_adapter(session_id, demo_adapter)
                except Exception:
                    pass
                return restored
        elif record and record.db_type.startswith("upload_"):
            db_path = DATA_DIR / f"{record.db_type}.db"
            if db_path.exists():
                from app.routers.connect_db import inspect_db_schema_and_samples
                table_names, schema_info, sample_values_map = inspect_db_schema_and_samples(db_path)
                restored = {
                    "db_type": "upload",
                    "upload_name": record.db_type,
                    "db_path": db_path,
                    "database_url": f"sqlite:///{db_path.as_posix()}",
                    "tables": table_names,
                    "schema": schema_info,
                    "sample_values": sample_values_map,
                }
                SESSION_STORE[session_id] = restored
                try:
                    from app.database.manager import DatabaseConnectionManager
                    from app.database.sqlite_adapter import SQLiteAdapter
                    upload_adapter = SQLiteAdapter(database_url=f"sqlite:///{db_path.as_posix()}", db_path=db_path)
                    DatabaseConnectionManager.register_adapter(session_id, upload_adapter)
                except Exception:
                    pass
                return restored
    except Exception:
        pass

    return None


def set_session(session_id: str, data: Dict[str, Any]) -> None:
    """Store session data for session_id and build its FAISS RAG index."""
    SESSION_STORE[session_id] = data
    try:
        from app.services.rag_service import build_schema_index
        tables = data.get("tables", [])
        schema = data.get("schema", {})
        sample_values = data.get("sample_values", {})
        if tables and schema:
            build_schema_index(session_id, tables, schema, sample_values)
    except Exception:
        pass
