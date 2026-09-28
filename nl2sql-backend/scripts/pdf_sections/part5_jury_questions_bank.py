"""Part 5: Sections 17 through 20
- SECTION 17: Important Technical Components (Jury Must Know Reference Table)
- SECTION 18: Comprehensive Technical Jury Question Bank (Categories A through R)
- SECTION 19: Adversarial Hard Jury Cross-Questions & Architectural Defenses
- SECTION 20: 'Show Me The Code' Codebase Inspection Walkthroughs
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
    jury_q,
    STYLES,
    C_TEAL,
    C_BLUE,
    C_BG_CARD,
    C_BORDER,
)


def build_part5():
    story = []

    # =========================================================================
    # SECTION 17: IMPORTANT TECHNICAL COMPONENTS (JURY MUST KNOW)
    # =========================================================================
    story.extend(sec_header(17, "Important Technical Components (Jury Must Know)"))
    story.append(p(
        "Before entering the technical defense room, master the exact technical definitions, codebase locations, "
        "and architectural importance of the following twelve core components."
    ))

    must_know_table = [
        ["Component", "Technical Definition", "Code Location", "Architectural Importance", "Anticipated Jury Question"],
        ["AST Validator", "sqlglot Abstract Syntax Tree parser checking syntax and statement nodes.", "app/services/sql_validator.py", "Prevents SQL injection and blocks destructive DDL.", "'Why not just use regular expressions to block DROP TABLE?'"],
        ["Schema-Aware RAG", "Dense semantic vector retrieval using SentenceTransformers + FAISS.", "app/services/rag_service.py", "Prevents token bloat on large schemas (> 4 tables).", "'How does the vector index know which tables to retrieve?'"],
        ["Two-Tier Rate Limiter", "In-memory sliding window rate limiter: 20 req/min session, 100 global.", "app/routers/query.py", "Shields backend and Gemini API from denial-of-service hammering.", "'How do you prevent memory leaks from inactive sessions?'"],
        ["Two-Phase Write Staging", "In-memory staging buffer (_PENDING_WRITES) requiring explicit confirmation.", "app/routers/query.py", "Eliminates risk of accidental database mutations.", "'What stops an attacker from executing another user's write?'"],
        ["Self-Correction Loop", "Iterative feedback loop (up to 3 retries) feeding errors back to LLM.", "app/routers/query.py", "Heals syntax anomalies and column mismatches autonomously.", "'How does self-correction prevent infinite retry loops?'"],
        ["Universal DB Adapter", "Object-oriented abstraction pattern (BaseDatabaseAdapter).", "app/database/base.py", "Allows uniform querying across SQLite and PostgreSQL.", "'Can this system query remote enterprise databases?'"],
        ["Zero-Result Reasoning", "Evaluates zero-row SELECT queries against schema sample values.", "app/services/sql_generator.py", "Explains *why* no data matched rather than showing a blank table.", "'How do you tell the difference between a bug and empty data?'"],
        ["Unicode Language Gate", "Unicode block scanner (\\u0B80-\\u0BFF) & Thanglish lexicon matcher.", "app/services/sql_generator.py", "Enforces native Tamil and Thanglish multilingual translation.", "'How do you detect Tamil if the user writes in English script?'"],
        ["Duplicate INSERT Check", "AST inspection + parameterized SELECT 1 pre-check before inserting.", "app/services/execution_engine.py", "Prevents duplicate records in tables lacking unique constraints.", "'How do you prevent duplicate data from multiple clicks?'"],
        ["Path Masking Regex", "Regular expression stripping filesystem paths from error messages.", "app/services/execution_engine.py", "Prevents local filesystem path disclosure.", "'Do error messages expose internal server file structures?'"],
        ["SQLite WAL Pragma", "Write-Ahead Logging mode (PRAGMA journal_mode=WAL).", "app/models/meta_db.py", "Enables concurrent readers without blocking writes.", "'Doesn't SQLite lock the entire database during writes?'"],
        ["Deterministic Cache", "SHA-256 hashed response cache with 10-min TTL and write invalidation.", "app/services/sql_generator.py", "Achieves sub-millisecond responses on repeated queries.", "'How do you ensure cached results don't show stale data?'"],
    ]
    story.append(make_table(must_know_table, [65, 110, 105, 115, 125]))
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 18: TECHNICAL JURY QUESTIONS (CATEGORIES A THROUGH R)
    # =========================================================================
    story.extend(sec_header(18, "Technical Jury Question Bank (Categories A through R)"))
    story.append(p(
        "This section provides comprehensive, code-referenced answers to eighteen critical jury questions "
        "spanning all software engineering, AI/ML, security, and database disciplines."
    ))

    # Question A: Architecture
    story.extend(jury_q(
        "A",
        "Explain the high-level architecture of your project and why it is designed as a decoupled SPA.",
        "Our system uses a decoupled three-tier architecture: a React Single Page Application frontend communicating over RESTful HTTP with a Python FastAPI backend, which interfaces through universal database adapters to local or remote relational engines.",
        "A decoupled architecture cleanly isolates UI rendering and Web Speech audio capture from heavy AI orchestration and database transactions. The FastAPI backend serves as a stateless ASGI application gateway, enforcing security headers, two-tier sliding window rate limiting, and AST parsing before any database interaction occurs. This enables independent scaling, unit testing of backend services without UI overhead, and future migration to mobile or CLI clients.",
        "ARCHITECTURE.md: High-Level Overview | app/main.py"
    ))

    # Question B: Code-Level
    story.extend(jury_q(
        "B",
        "How do you split multi-statement SQL strings and ensure they execute safely?",
        "We use sqlglot.parse(sql, read='sqlite') to parse statements into distinct AST trees, ensuring semicolons within quoted string literals are never mistaken for statement delimiters.",
        "In app/services/execution_engine.py, split_sql_statements() leverages sqlglot to parse the SQL text. Each statement in the resulting AST is individually transpiled and executed sequentially within a single transactional context (with conn:). If any statement raises an exception, the entire transaction rolls back atomically.",
        "app/services/execution_engine.py: split_sql_statements()"
    ))

    # Question C: Backend
    story.extend(jury_q(
        "C",
        "Why did you choose FastAPI over Flask or Django?",
        "FastAPI delivers native asynchronous ASGI performance, automatic OpenAPI documentation, and strict runtime type validation through Pydantic v2 with zero boilerplate.",
        "Flask is synchronous by default and requires external extensions for request schema validation and documentation. Django is a heavyweight monolithic framework with an ORM tightly coupled to server-rendered templates. FastAPI provides lightweight, high-performance ASGI throughput with native async support, ideal for handling concurrent LLM streaming and database I/O.",
        "app/main.py | app/routers/query.py"
    ))

    # Question D: Frontend
    story.extend(jury_q(
        "D",
        "How does the frontend handle real-time chart rendering and visualization recommendations?",
        "Our ChartPanel component dynamically evaluates the response payload's chart_type and data shape, instantiating Chart.js bar charts, line graphs, or KPI cards via HTML5 Canvas.",
        "When the backend returns query results, the chart_type field specifies the visualization heuristic ('bar', 'line', 'kpi', 'table'). In frontend/src/components/ChartPanel.jsx, the component inspects column datatypes and row cardinality. If numeric values represent sequential time series, it renders a Line chart; if categorical groupings, a Bar chart; if a single scalar, a KPI metric card.",
        "frontend/src/components/ChartPanel.jsx | MessageBubble.jsx"
    ))

    # Question E: API
    story.extend(jury_q(
        "E",
        "How is the /api/query endpoint secured against abusive request volume?",
        "We implement an in-memory two-tier sliding window rate limiter enforcing 20 requests per minute per session, and 100 requests per minute globally across all sessions.",
        "In app/routers/query.py, check_rate_limit() maintains timestamp queues. It first checks the global key '__global__' against a 100 req/60s ceiling to prevent distributed quota depletion. Next, it validates the individual session_id against a 20 req/60s ceiling. Any violation immediately raises an HTTP 429 exception with an explicit Retry-After header. Crucially, expired timestamps are actively deleted on each call to prevent dictionary memory leaks.",
        "app/routers/query.py: check_rate_limit()"
    ))

    # Question F: Database
    story.extend(jury_q(
        "F",
        "How does your system prevent SQLite concurrency locking issues during high-volume reads?",
        "We configure SQLite in Write-Ahead Logging mode via PRAGMA journal_mode=WAL and PRAGMA synchronous=NORMAL on engine connection.",
        "Default SQLite uses rollback journals that acquire an exclusive lock during writes, blocking all concurrent read queries. By executing PRAGMA journal_mode=WAL in app/models/meta_db.py via SQLAlchemy connection events, write operations append to a separate WAL file, allowing concurrent readers to read from the main database file without blocking or waiting.",
        "app/models/meta_db.py: set_sqlite_pragma()"
    ))

    # Question G: AI/ML
    story.extend(jury_q(
        "G",
        "How does your schema-aware RAG vector search work, and when is it bypassed?",
        "We embed table schemas into 384-dimensional dense vectors using SentenceTransformers and index them in FAISS IndexFlatIP; for small schemas with 4 or fewer tables, RAG is bypassed to conserve memory.",
        "In app/services/rag_service.py, build_schema_index() generates textual table summaries containing table names, column types, and sample values. When total tables > 4, FAISS computes exact cosine similarity against the user query, returning the top-4 most relevant tables. For schemas <= 4 tables, RAG is bypassed, returning all tables directly. This prevents over-filtering small databases and saves 150MB+ RAM on container cold-starts.",
        "app/services/rag_service.py: retrieve_relevant_tables()"
    ))

    # Question H: NLP
    story.extend(jury_q(
        "H",
        "How do you support native Tamil script and Thanglish without specialized translation APIs?",
        "We use character-level Unicode block inspection for Tamil script and lexical token matching against a colloquial Tamil dictionary for Thanglish, passing language instructions directly into the LLM system prompt.",
        "In app/services/sql_generator.py, detect_input_language() scans characters for Unicode range \\u0B80-\\u0BFF. If present, detected_language is set to 'tamil'. For Latin text, it checks token intersections against a Thanglish vocabulary set ('vayasuku', 'kaatunga', 'kudu', 'pannu'). The prompt instructs Gemini to output explanations and clarifications in pure Tamil script or Thanglish, validated by an automated translation fallback loop.",
        "app/services/sql_generator.py: detect_input_language()"
    ))

    # Question I: Security
    story.extend(jury_q(
        "I",
        "How do you stop SQL injection attacks attempting comment-based or stacked-statement bypasses?",
        "We strip quoted string literals first, reject any query containing comment syntax (-- or /* */), and parse the remainder with sqlglot to reject multi-statement payloads.",
        "Attackers often use SQL comments (e.g. SELECT * FROM users -- ; DROP TABLE...) to truncate safety checks. In app/services/sql_validator.py, _strip_strings() replaces string literals with empty quotes so valid apostrophes are not flagged. If '--' or '/*' appears in the remaining code, validate_sql() halts with 'injection_detected'. Furthermore, sqlglot parses the query into statement trees; if more than one statement exists, it is rejected.",
        "app/services/sql_validator.py: validate_sql()"
    ))

    # Question J: Performance
    story.extend(jury_q(
        "J",
        "What is your query caching strategy and how do you ensure cache consistency across data modifications?",
        "We implement an in-memory response cache keyed by a deterministic SHA-256 hash of the schema signature, question, language, and context, invalidated immediately upon any confirmed write mutation.",
        "In app/services/sql_generator.py, _generate_cache_key() computes a 16-character SHA-256 hash incorporating the schema structure and normalized question. Cached responses have a 10-minute TTL. Crucially, whenever confirm_write() executes an INSERT, UPDATE, or DELETE in app/routers/query.py, clear_query_cache() is immediately triggered, guaranteeing that subsequent SELECT queries never return stale data.",
        "app/services/sql_generator.py: _QUERY_CACHE | app/routers/query.py: confirm_write()"
    ))

    # Question K: Scalability
    story.extend(jury_q(
        "K",
        "What is your architectural bottleneck if user traffic scales to 10,000 concurrent users?",
        "Our primary bottlenecks would be in-memory state storage (rate limiter, session cache, write buffer) and synchronous database driver execution on a single ASGI node.",
        "To scale to 10,000 users, we would migrate in-memory state (_QUERY_TIMESTAMPS, _QUERY_CACHE, _PENDING_WRITES) to a distributed Redis cluster, migrate synchronous SQLite adapter calls to asynchronous drivers (aiosqlite and asyncpg), deploy Uvicorn across an autoscaling container cluster (AWS ECS/EKS), and point read queries to PostgreSQL read replicas.",
        "LIMITATIONS.md: Section 1.2 & Section 2"
    ))

    # Question L: Deployment
    story.extend(jury_q(
        "L",
        "Explain how your Dockerfile optimizes image size and runtime RAM usage.",
        "We use a multi-stage Docker build separating Node asset compilation from a Python slim runtime, installing CPU-only PyTorch to avoid 3.5GB of CUDA bloat.",
        "Stage 1 compiles React assets with Node 20. Stage 2 copies the pre-built dist folder into python:3.11-slim. It installs PyTorch using --index-url https://download.pytorch.org/whl/cpu, reducing the image size from 4.5GB to ~650MB. Runtime flags like OMP_NUM_THREADS=1 clamp background thread pools, keeping the container comfortably inside Render's 512MB RAM free-tier limit.",
        "Dockerfile: Stages 1 and 2"
    ))

    # Question M: Debugging
    story.extend(jury_q(
        "M",
        "How does the autonomous self-correction loop heal a query that fails with an unknown column error?",
        "The execution engine catches sqlite3.OperationalError, extracts the database error string, and passes the failed SQL along with the error message back to Gemini in regenerate_sql() for automated correction.",
        "In app/routers/query.py, the while attempt <= MAX_RETRIES loop intercepts database execution errors in Step B. If the database returns 'no such column: pat_name', regenerate_sql() injects this exact error into a targeted correction prompt. Gemini synthesizes corrected SQL referencing the valid column 'name', which is re-validated and re-executed. The turn is logged in query_history with self_corrected=1.",
        "app/routers/query.py: lines 617-658 | app/services/sql_generator.py: regenerate_sql()"
    ))

    # Question N: Design Decisions
    story.extend(jury_q(
        "N",
        "Why do you stage write mutations in memory rather than executing them inside a temporary staging table?",
        "In-memory staging in _PENDING_WRITES requires zero database schema alterations, zero temporary table cleanup overhead, and completely isolates unconfirmed mutations from the database engine.",
        "Creating temporary staging tables requires executing DDL on the connected database, which alters schema state, creates race conditions among concurrent sessions, and risks orphaned tables on disconnect. Staging the validated SQL text and explanation in _PENDING_WRITES with a short expiration lifecycle guarantees that the database engine remains untouched until the user explicitly confirms.",
        "app/routers/query.py: _PENDING_WRITES"
    ))

    # Question O: Project Limitations
    story.extend(jury_q(
        "O",
        "What are the honest technical limitations of this project?",
        "Our system requires Chromium-based browsers for Web Speech API transcription, relies on single-node in-memory state for rate limiting and write buffers, and currently supports PostgreSQL via synchronous SQLAlchemy drivers rather than native async drivers.",
        "In LIMITATIONS.md, we document that non-Chromium browsers must fall back to text input, server restarts clear unconfirmed staged writes, and high-concurrency production requires an external Redis state store. We adhere strictly to engineering honesty rather than claiming unverified capabilities.",
        "LIMITATIONS.md: Section 1"
    ))

    # Question P: "Why X instead of Y?"
    story.extend(jury_q(
        "P",
        "Why did you use Gemini Flash-Lite instead of OpenAI GPT-4o or local Ollama?",
        "Gemini Flash-Lite offers superior token latency (<1s response), high rate limits on developer tiers, native Tamil multilingual fluency, and zero host GPU memory consumption.",
        "GPT-4o introduces higher API latency and cost per token. Hosting a local Ollama LLM (e.g. CodeLlama 13B) requires at least 8GB of Dedicated GPU VRAM, which is impossible on cost-effective cloud containers like Render 512MB RAM. Gemini Flash-Lite provides the ideal balance of speed, cost, and multilingual accuracy.",
        "app/services/sql_generator.py: MODELS_TO_TRY"
    ))

    # Question Q: Hard Cross-Questions
    story.extend(jury_q(
        "Q",
        "What prevents a malicious user from approving a staged write that belongs to another active user's session?",
        "Our confirm_write endpoint strictly verifies that payload.session_id matches the session_id stored in the staged _PENDING_WRITES dictionary, returning HTTP 403 Forbidden on any mismatch.",
        "In app/routers/query.py line 774, when POST /api/confirm-write is called, the handler checks if pending.get('session_id') != payload.session_id. If a user attempts to guess or submit another session's query_id, the request is blocked immediately with HTTP 403, and the attempt is logged as an unauthorized security event.",
        "app/routers/query.py: lines 772-785"
    ))

    # Question R: Code Walkthrough
    story.extend(jury_q(
        "R",
        "Show me exactly where you prevent duplicate records from being inserted into the database.",
        "In app/services/execution_engine.py, check_duplicate_insert() parses the INSERT AST, extracts columns and values, and executes a parameterized SELECT 1 pre-check before inserting.",
        "Lines 94-152 of execution_engine.py inspect the incoming statement using sqlglot.exp.Insert. It extracts target table and column names, builds a parameterized query 'SELECT 1 FROM table WHERE col1=? AND col2=? LIMIT 1', and executes it with the literal values. If a matching row already exists, execution is skipped and a notice is returned, preventing duplicate records even if the table lacks a UNIQUE constraint.",
        "app/services/execution_engine.py: check_duplicate_insert()"
    ))

    # =========================================================================
    # SECTION 19: ADVERSARIAL JURY CROSS-QUESTIONS
    # =========================================================================
    story.extend(sec_header(19, "Adversarial Hard Jury Cross-Questions"))
    story.append(p(
        "These cross-questions simulate aggressive challenges from cynical software architects and AI reviewers. "
        "Each scenario provides an unassailable engineering defense grounded in the actual codebase."
    ))

    story.append(sub_header("Cross-Question 1: 'LLMs hallucinate. Why should any enterprise trust your SQL queries?'"))
    story.append(p(
        "<b>Verbal Rebuttal:</b> &ldquo;We never trust the LLM's raw output. The LLM acts solely as a semantic proposal engine; "
        "every query must pass three deterministic gates—Schema Grounding, AST Security Validation, and Transactional Execution—before reaching data.&rdquo;<br/>"
        "<b>Deep Engineering Defense:</b><br/>"
        "1. <i>Schema Grounding:</i> The LLM prompt is dynamically populated with verified table names, column data types, and distinct sample values extracted directly via <code>PRAGMA table_info</code> and <code>information_schema</code>. The LLM is never allowed to guess column names.<br/>"
        "2. <i>Boundary Checking:</i> Before synthesis, our ambiguity and data-availability gates reject out-of-schema queries (e.g. asking for airline flights on a hospital database) with <code>data_available: false</code>.<br/>"
        "3. <i>AST Validation:</i> <code>sqlglot</code> parses the proposed query into an Abstract Syntax Tree, mathematically verifying that statement types match the session mode, rejecting destructive DDL, and verifying WHERE clauses.<br/>"
        "4. <i>Autonomous Self-Correction:</i> If a syntax or column error occurs, our retry loop feeds the exact SQLite operational error back to Gemini to repair the query automatically."
    ))

    story.append(sub_header("Cross-Question 2: 'What happens if a user asks a query in Thanglish that confuses Tamil and English words?'"))
    story.append(p(
        "<b>Verbal Rebuttal:</b> &ldquo;Our system treats Thanglish as a first-class citizen using a dual-mode token filter and conversational confirmation flow.&rdquo;<br/>"
        "<b>Deep Engineering Defense:</b> In <code>app/services/sql_generator.py</code>, <code>detect_input_language()</code> checks token sets against a compiled lexicon of colloquial Tamil particles (<code>kaatunga, vayasuku, kudunga, irukku</code>). When detected, the prompt instructs Gemini to translate the intent into standard SQL while returning an explanation acknowledging the colloquial phrasing. If a name is phonetically ambiguous, <code>find_near_miss_value()</code> intercepts the query and asks: <i>'Did you mean Dr. Priya Patel?'</i> before executing."
    ))

    story.append(sub_header("Cross-Question 3: 'What happens if the backend crashes while a write mutation is staged?'"))
    story.append(p(
        "<b>Verbal Rebuttal:</b> &ldquo;The system fails safely. Because mutations are staged in memory and only executed upon explicit confirmation, a crash results in zero uncommitted data mutations.&rdquo;<br/>"
        "<b>Deep Engineering Defense:</b> Staged write statements reside in the in-memory <code>_PENDING_WRITES</code> dictionary. If the Uvicorn server restarts, the dictionary clears. The database files remain completely intact. When the user attempts to confirm, the backend checks database history; if unexecuted, it prompts the user to re-submit the query. At no point is a half-written transaction left lingering."
    ))

    # =========================================================================
    # SECTION 20: "SHOW ME THE CODE" QUESTIONS
    # =========================================================================
    story.extend(sec_header(20, "'Show Me The Code' Codebase Inspection Walkthroughs"))
    story.append(p(
        "Be prepared for jury members who interrupt slides and demand: <i>'Open your editor and show me the exact line where this occurs.'</i>"
    ))

    story.append(sub_header("1. 'Show me where you strip SQL comments to prevent injection bypasses.'"))
    story.append(bullet("<b>File:</b> <code>nl2sql-backend/app/services/sql_validator.py</code>"))
    story.append(bullet("<b>Lines:</b> Lines 17-30 (<code>_strip_strings()</code> and <code>_strip_comments_and_strings()</code>) and Lines 59-66."))
    story.append(bullet("<b>Exact Code:</b> <code>without_strings = _strip_strings(sql_string); if '--' in without_strings or '/*' in without_strings: return {'valid': False, 'reason': 'injection_detected'}</code>"))

    story.append(sub_header("2. 'Show me where you enforce that UPDATE and DELETE must have a WHERE clause.'"))
    story.append(bullet("<b>File:</b> <code>nl2sql-backend/app/services/sql_validator.py</code>"))
    story.append(bullet("<b>Lines:</b> Lines 126-141."))
    story.append(bullet("<b>Exact Code:</b> <code>if isinstance(stmt, (exp.Update, exp.Delete)): if not stmt.find(exp.Where): return {'valid': False, 'reason': 'missing_where_clause', 'message': 'UPDATE/DELETE queries must include a WHERE clause for safety.'}</code>"))

    story.append(sub_header("3. 'Show me where you verify session ownership during write confirmations.'"))
    story.append(bullet("<b>File:</b> <code>nl2sql-backend/app/routers/query.py</code>"))
    story.append(bullet("<b>Lines:</b> Lines 773-784 and Lines 793-803."))
    story.append(bullet("<b>Exact Code:</b> <code>if pending.get('session_id') != payload.session_id: raise HTTPException(status_code=403, detail='Forbidden: This pending write query belongs to a different session.')</code>"))

    story.append(sub_header("4. 'Show me where you sanitize server file paths from database error messages.'"))
    story.append(bullet("<b>File:</b> <code>nl2sql-backend/app/services/execution_engine.py</code> & <code>app/database/sqlite_adapter.py</code>"))
    story.append(bullet("<b>Lines:</b> Lines 18-21 (regex definition) and Lines 80-85 of <code>execution_engine.py</code>."))
    story.append(bullet("<b>Exact Code:</b> <code>_FILE_PATH_RE = re.compile(r'(?:[a-zA-Z]:[\\\\/][^\\s:\"\\',;)]+|/(?:home|app|tmp|var|usr|etc|root|data)/[^\\s:\"\\',;)]+|[\\w./\\\\]+\\.(?:db|sqlite|sqlite3)\\b)', re.IGNORECASE); err_msg = _FILE_PATH_RE.sub('[database]', err_msg)</code>"))

    return story

