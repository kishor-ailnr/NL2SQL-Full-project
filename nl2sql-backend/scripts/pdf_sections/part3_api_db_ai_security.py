"""Part 3: Sections 8 through 11
- SECTION 8: RESTful API Endpoint Audit & Contracts
- SECTION 9: Relational Database Schema & Persistence Analysis
- SECTION 10: AI, LLM, RAG & Multilingual Engine Deep Dive
- SECTION 11: Comprehensive Security Architecture & Risk Audit
"""

from reportlab.platypus import Paragraph, Spacer, PageBreak, KeepTogether, Table, TableStyle
from reportlab.lib import colors
from .styles import (
    PRINTABLE_WIDTH,
    p,
    sec_header,
    sub_header,
    sub_sub_header,
    bullet,
    callout,
    code_box,
    ascii_diagram,
    make_table,
    STYLES,
    C_TEAL,
    C_BLUE,
    C_BG_CARD,
    C_BORDER,
)


def build_part3():
    story = []

    # =========================================================================
    # SECTION 8: API ANALYSIS
    # =========================================================================
    story.extend(sec_header(8, "RESTful API Endpoint Audit"))
    story.append(p(
        "The NL2SQL backend exposes a clean, strongly typed REST API implemented with FastAPI and Pydantic v2. "
        "The table below details every production endpoint, its HTTP verb, input contracts, response schemas, and handler functions."
    ))

    api_table = [
        ["Method", "Endpoint", "File & Handler", "Input Payload", "Response Schema", "Status Codes"],
        ["POST", "/api/connect-db", "connect_db.py: connect_db()", "{db_type, demo_name, connection_string}", "{session_id, status, tables, schema}", "200, 400, 500"],
        ["POST", "/api/upload-data", "connect_db.py: upload_data()", "Multipart form: file (.csv / .sql)", "{session_id, status, tables, schema}", "200, 400, 413, 500"],
        ["GET", "/api/session-status", "connect_db.py: get_session_status()", "Query: ?session_id=<uuid>", "{valid, status, session_id, tables, schema}", "200, 400, 404"],
        ["GET", "/api/schema/{session_id}", "connect_db.py: get_schema()", "Path: session_id", "{session_id, tables, schema}", "200, 404"],
        ["POST", "/api/disconnect", "connect_db.py: disconnect_db()", "{session_id}", "{status: 'disconnected'}", "200, 400"],
        ["POST", "/api/query", "query.py: handle_query()", "{session_id, conversation_id, text, language}", "{query_id, sql, explanation, result, chart_type, ...}", "200, 404, 429, 500"],
        ["POST", "/api/confirm-write", "query.py: confirm_write()", "{session_id, query_id, confirmed}", "{status, rows_affected, result, chart_type, notice}", "200, 403, 404, 429"],
        ["POST", "/api/conversations/new", "conversations.py: create_conversation()", "{session_id}", "{conversation_id, created_at}", "200, 400, 500"],
        ["GET", "/api/conversations", "conversations.py: list_conversations()", "Query: ?session_id=<uuid>", "{conversations: [{id, title, created_at}]}", "200, 500"],
        ["GET", "/api/conversations/{id}/messages", "conversations.py: get_conversation_messages()", "Path: conversation_id", "{messages: [{nl_query, sql, explanation, result}]}", "200, 404, 500"],
        ["DELETE", "/api/conversations/{id}", "conversations.py: delete_conversation()", "Path: conversation_id", "{status: 'deleted'}", "200, 404, 500"],
        ["GET", "/health", "main.py: health_check()", "None", "{status: 'ok'}", "200"],
    ]
    story.append(make_table(api_table, [45, 105, 105, 110, 115, 40]))
    story.append(Spacer(1, 10))

    story.append(sub_header("8.1 Deep Endpoint Breakdown: POST /api/query"))
    story.append(p(
        "<b>HTTP Method:</b> POST | <b>Endpoint:</b> <code>/api/query</code> | <b>Handler:</b> <code>app/routers/query.py: handle_query()</code><br/>"
        "<b>Request Headers:</b> <code>Content-Type: application/json</code><br/>"
        "<b>Request Body Schema (QueryRequest):</b><br/>"
        "&nbsp;&nbsp;&bull; <code>session_id (str, required)</code>: UUID of active database session.<br/>"
        "&nbsp;&nbsp;&bull; <code>conversation_id (str, optional)</code>: UUID of active thread; auto-creates thread if null.<br/>"
        "&nbsp;&nbsp;&bull; <code>text (str, required)</code>: Natural language question or voice transcription.<br/>"
        "&nbsp;&nbsp;&bull; <code>language (str, default 'auto')</code>: Language hint ('auto', 'english', 'tamil', 'thanglish').<br/>"
        "<b>Response Body Schema (QueryResponse):</b><br/>"
        "&nbsp;&nbsp;&bull; <code>query_id (str)</code>: Integer/UUID identifying the query in history.<br/>"
        "&nbsp;&nbsp;&bull; <code>sql (str | null)</code>: Synthesized and validated SQL statement.<br/>"
        "&nbsp;&nbsp;&bull; <code>explanation (str | null)</code>: Natural language explanation in detected language.<br/>"
        "&nbsp;&nbsp;&bull; <code>confidence (float)</code>: Model confidence score (0.0 to 1.0).<br/>"
        "&nbsp;&nbsp;&bull; <code>query_type (str)</code>: 'select', 'write', 'clarification', 'confirmation', 'unavailable'.<br/>"
        "&nbsp;&nbsp;&bull; <code>result (List[Dict])</code>: Executed row records as list of dictionaries.<br/>"
        "&nbsp;&nbsp;&bull; <code>chart_type (str)</code>: Visualization recommendation ('bar', 'line', 'kpi', 'table', 'none').<br/>"
        "&nbsp;&nbsp;&bull; <code>self_corrected (bool)</code>: True if initial SQL failed and was repaired in retry loop.<br/>"
        "&nbsp;&nbsp;&bull; <code>data_available (bool)</code>: False if query requests entities absent from schema.<br/>"
        "<b>Security Checks:</b> Two-tier sliding window rate limit (20 req/min per session, 100 req/min global); AST safety gate via <code>validate_sql()</code>; path sanitization in error returns.<br/>"
        "<b>Status Codes:</b> <code>200 OK</code>, <code>404 Not Found</code> (session missing), <code>429 Too Many Requests</code> (rate limit exceeded), <code>500 Internal Error</code>."
    ))

    # =========================================================================
    # SECTION 9: DATABASE ANALYSIS
    # =========================================================================
    story.extend(sec_header(9, "Database Analysis & Persistence Architecture"))
    story.append(p(
        "The system segregates persistence into two distinct domains: (1) internal system metadata (<code>meta.db</code>), and "
        "(2) connected domain databases (demo SQLite files, user CSV/SQL uploads, or remote PostgreSQL databases)."
    ))

    story.append(sub_header("9.1 System Metadata Database Schema (meta.db)"))
    story.append(p(
        "<code>meta.db</code> is managed via SQLAlchemy ORM with SQLite Write-Ahead Logging (<code>PRAGMA journal_mode=WAL</code>). "
        "It consists of three core relational tables:"
    ))
    story.append(bullet("<b>sessions:</b> <code>id (VARCHAR PK)</code>, <code>db_type (VARCHAR)</code>, <code>connected_at (DATETIME)</code>."))
    story.append(bullet("<b>conversations:</b> <code>id (VARCHAR PK)</code>, <code>session_id (VARCHAR FK &rarr; sessions.id)</code>, <code>title (VARCHAR)</code>, <code>created_at (DATETIME)</code>."))
    story.append(bullet("<b>query_history:</b> <code>id (INTEGER PK AUTOINCREMENT)</code>, <code>session_id (VARCHAR FK)</code>, <code>conversation_id (VARCHAR FK)</code>, <code>nl_query (TEXT)</code>, <code>generated_sql (TEXT)</code>, <code>explanation (TEXT)</code>, <code>result_json (TEXT)</code>, <code>chart_type (VARCHAR)</code>, <code>confidence (FLOAT)</code>, <code>query_type (VARCHAR)</code>, <code>self_corrected (INTEGER)</code>, <code>correction_attempts (INTEGER)</code>, <code>corrections_json (TEXT)</code>, <code>created_at (DATETIME)</code>."))

    story.append(sub_header("9.2 Demo Datasets Relational Schemas"))
    story.append(sub_sub_header("Hospital Demo Database (demo_hospital.db)"))
    story.append(p(
        "Relational schema modeling an active inpatient hospital facility:<br/>"
        "&bull; <code>patients:</code> patient_id (PK), name, age, gender, admission_date, diagnosis, room_number, doctor_id (FK &rarr; doctors.doctor_id).<br/>"
        "&bull; <code>doctors:</code> doctor_id (PK), name, specialization, phone, email, department.<br/>"
        "&bull; <code>appointments:</code> appointment_id (PK), patient_id (FK &rarr; patients), doctor_id (FK &rarr; doctors), appointment_date, status, reason.<br/>"
        "&bull; <code>departments:</code> department_id (PK), name, head_of_department, budget, phone.<br/>"
        "&bull; <code>bills:</code> bill_id (PK), patient_id (FK &rarr; patients), amount, bill_date, status, payment_method."
    ))

    story.append(sub_sub_header("E-Commerce Demo Database (demo_ecommerce.db)"))
    story.append(p(
        "Relational schema modeling an omnichannel retail operation:<br/>"
        "&bull; <code>customers:</code> customer_id (PK), name, email, phone, city, join_date, tier.<br/>"
        "&bull; <code>products:</code> product_id (PK), name, category_id (FK &rarr; categories), price, stock_quantity, rating.<br/>"
        "&bull; <code>categories:</code> category_id (PK), name, description.<br/>"
        "&bull; <code>orders:</code> order_id (PK), customer_id (FK &rarr; customers), order_date, total_amount, status, shipping_address.<br/>"
        "&bull; <code>order_items:</code> item_id (PK), order_id (FK &rarr; orders), product_id (FK &rarr; products), quantity, unit_price."
    ))

    db_erd_diag = """
+--------------------+           +----------------------+           +--------------------+
|     DOCTORS        |           |      PATIENTS        |           |      BILLS         |
|--------------------|           |----------------------|           |--------------------|
| PK doctor_id       |<----+     | PK patient_id        |<----+     | PK bill_id         |
|    name            |     |     |    name              |     |     | FK patient_id -----+
|    specialization  |     |     |    age / gender      |     |     |    amount          |
|    department      |     |     |    diagnosis         |     |     |    status          |
+--------------------+     |     | FK doctor_id --------+     |     +--------------------+
                           |     +----------------------+     |
                           |                 ^                |
                           |                 |                |
                           |     +-----------+----------+     |
                           |     |     APPOINTMENTS     |     |
                           |     |----------------------|     |
                           |     | PK appointment_id    |     |
                           +-----| FK doctor_id         |     |
                                 | FK patient_id -------------+
                                 |    appointment_date  |
                                 +----------------------+
"""
    story.extend(ascii_diagram(db_erd_diag, "Hospital Database Entity-Relationship Diagram (ERD)"))

    # =========================================================================
    # SECTION 10: AI, ML, RAG & NLP ANALYSIS
    # =========================================================================
    story.extend(sec_header(10, "AI, ML, RAG & Multilingual Engine"))
    story.append(p(
        "The AI architecture utilizes a multi-stage hybrid approach combining dense vector retrieval, deterministic NLP "
        "pre-processing, and instruction-tuned large language model synthesis."
    ))

    story.append(sub_header("10.1 Primary LLM: Google Gemini Flash-Lite Architecture"))
    story.append(p(
        "<b>Model Tier:</b> <code>gemini-3.1-flash-lite</code> (with dynamic fallback to <code>gemini-flash-latest</code>, "
        "<code>gemini-3.5-flash-lite</code>, and <code>gemini-3.6-flash</code>).<br/>"
        "<b>Inference Parameters:</b> Temperature is fixed at <code>0.1</code> to enforce mathematical determinism and eliminate "
        "creative variance in SQL generation. The model is called using REST transport.<br/>"
        "<b>Prompt Engineering & Schema Grounding:</b> The system prompt explicitly enforces dialect rules, passes table column "
        "types, primary keys, foreign keys, and distinct sample values (e.g. <code>'Active', 'Pending', 'Cancelled'</code>), "
        "enabling Gemini to write accurate <code>WHERE status = 'Pending'</code> clauses without guessing column casing or abbreviations.<br/>"
        "<b>Output Constraint:</b> Generates pure RFC-8259 compliant JSON strings matching a strict schema, stripped of markdown fences."
    ))

    story.append(sub_header("10.2 Schema-Aware Vector RAG (SentenceTransformers + FAISS)"))
    story.append(p(
        "Located in <code>app/services/rag_service.py</code>:<br/>"
        "&bull; <b>Embedding Model:</b> <code>all-MiniLM-L6-v2</code> mapping table summaries to 384-dimensional dense vectors.<br/>"
        "&bull; <b>Vector Index:</b> FAISS <code>IndexFlatIP</code> (Inner Product over L2-normalized embeddings, calculating exact cosine similarity).<br/>"
        "&bull; <b>Adaptive Schema Threshold:</b> Schemas with &le; 4 tables bypass embedding generation entirely to conserve server RAM "
        "(critical for Render free-tier 512MB limits) and prevent over-filtering small databases. Schemas with > 4 tables retrieve the top-4 relevant tables."
    ))

    story.append(sub_header("10.3 Trilingual NLP & Phonetic Correction Engine"))
    story.append(p(
        "Located in <code>app/services/sql_generator.py</code>:<br/>"
        "&bull; <b>Tamil Script Detection:</b> Inspects text characters against the Unicode Tamil block range: "
        "<code>any('\\u0B80' &le; c &le; '\\u0BFF' for c in text)</code>.<br/>"
        "&bull; <b>Thanglish Vocabulary Matching:</b> Matches token sets against common colloquial Tamil transliteration particles "
        "(<code>vayasuku, mela, keela, kaatunga, kudu, pannunga, yaaru, noiyali</code>).<br/>"
        "&bull; <b>Phonetic Correction:</b> Uses <code>difflib.SequenceMatcher</code> against schema sample values to detect near-miss "
        "spoken terms (e.g. voice input 'Harini' matched to patient 'Harini Krishnan' with similarity &ge; 0.75), triggering confirmation."
    ))

    # =========================================================================
    # SECTION 11: SECURITY ANALYSIS
    # =========================================================================
    story.extend(sec_header(11, "Comprehensive Security Architecture"))
    story.append(p(
        "NL2SQL implements defense-in-depth across six distinct architectural layers, ensuring that no single component failure "
        "can compromise host integrity or database security."
    ))

    sec_table = [
        ["Threat Vector", "Vulnerability Description", "Mitigation Mechanism in Codebase", "Implementation Location"],
        ["SQL Injection", "Attacker appends stacked statements: '; DROP TABLE patients;'", "sqlglot AST parse rejects multi-statement strings and comments", "sql_validator.py: validate_sql()"],
        ["Accidental Mutation", "LLM generates unconstrained UPDATE/DELETE without WHERE", "AST traversal enforces stmt.find(exp.Where) for all mutations", "sql_validator.py: validate_sql()"],
        ["Unauthorized Writes", "Direct execution of destructive write commands via chat", "Strict read-only default; mutations staged in memory for user confirmation", "query.py: _PENDING_WRITES buffer"],
        ["Cross-Session Execution", "Session B attempts to confirm a staged write staged by Session A", "Authorization gate validates pending['session_id'] == payload.session_id", "query.py: confirm_write() line 774"],
        ["Replay Attacks", "Attacker submits repeated confirm-write calls to duplicate writes", "Atomic pop (_PENDING_WRITES.pop) guarantees single-use execution", "query.py: confirm_write() line 830"],
        ["DoS & Quota Exhaustion", "Script hammers Gemini API with automated requests", "Two-tier sliding window rate limiter: 20 req/min session, 100 req/min global", "query.py: check_rate_limit()"],
        ["Path Disclosure", "Database exceptions leak internal server disk paths", "Regex _FILE_PATH_RE sanitizes file paths to '[database]'", "sqlite_adapter.py & execution_engine.py"],
        ["Malicious Uploads", "Attacker uploads executable files or massive dumps", "5MB size ceiling, .csv/.sql whitelist, table name sanitization", "connect_db.py: upload_data()"],
        ["Clickjacking / XSS", "Embedding application inside malicious iframes", "SecurityHeadersMiddleware attaches CSP, nosniff, DENY, Referrer-Policy", "main.py: SecurityHeadersMiddleware"],
    ]
    story.append(make_table(sec_table, [85, 110, 185, 140]))
    story.append(Spacer(1, 10))

    return story

