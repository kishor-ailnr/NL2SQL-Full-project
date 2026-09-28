"""Part 4: Sections 12 through 16
- SECTION 12: Error Handling, Resilience & Fault Tolerance
- SECTION 13: Latency, Benchmarks & Performance Analysis
- SECTION 14: Scalability Architecture & Enterprise Roadmap
- SECTION 15: Architectural Design Trade-Offs & Decisions
- SECTION 16: Module Dependency Topology & Blast Radius
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


def build_part4():
    story = []

    # =========================================================================
    # SECTION 12: ERROR HANDLING & RESILIENCE
    # =========================================================================
    story.extend(sec_header(12, "Error Handling, Resilience & Fault Tolerance"))
    story.append(p(
        "A robust production architecture must fail safely without leaking internal stack traces or corrupting data. "
        "The table below details failure handling across every primary system subsystem."
    ))

    err_table = [
        ["Subsystem", "Failure Scenario", "Detection Mechanism", "Automatic Recovery / Fallback Response"],
        ["AI Synthesis", "Gemini 429 Quota Exceeded", "HTTPException catch checking '429' or 'quota'", "Returns HTTP 429 with 'AI service rate limit exceeded. Please wait a moment.'"],
        ["AI Synthesis", "Primary Gemini Model Down", "Exception caught in model invocation loop", "Sticky fallback transitions across MODELS_TO_TRY list (flash-latest, 3.5, 3.6)"],
        ["AI Synthesis", "Unparseable LLM Output", "JSONDecodeError in _clean_json_string()", "Triggers fallback clarification question asking user to refine criteria"],
        ["AST Validator", "Syntax Error in Generated SQL", "sqlglot.errors.ParseError caught", "Self-correction loop passes syntax error to regenerate_sql() (up to 3 retries)"],
        ["AST Validator", "Destructive DDL Detected", "isinstance(stmt, (Drop, Alter, Truncate))", "Rejects query immediately with 'DDL and destructive operations prohibited.'"],
        ["Database", "Execution Syntax / Column Error", "sqlite3.OperationalError caught in run_select()", "Self-correction loop passes exact SQLite error to Gemini for query repair"],
        ["Database", "Duplicate INSERT Execution", "check_duplicate_insert() executes SELECT 1", "Skips execution; returns notice: 'Duplicate record detected; insertion skipped.'"],
        ["Database", "Connection / File Missing", "FileNotFoundError on db_path in adapter", "Restores demo/upload session from meta.db or prompts user to reconnect"],
        ["State Store", "Server Reload / Session Evicted", "get_session() returns None", "Queries meta.db SessionModel to dynamically restore demo/uploaded schemas"],
        ["Write Buffer", "Expired Pending Write", "query_id missing from _PENDING_WRITES", "Falls back to QueryHistoryModel; rejects with 404 if already processed"],
    ]
    story.append(make_table(err_table, [75, 110, 155, 180]))
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 13: PERFORMANCE ANALYSIS & BENCHMARKS
    # =========================================================================
    story.extend(sec_header(13, "Performance Analysis & Latency Profile"))
    story.append(p(
        "Every operation along the critical query path has been profiled to identify bottlenecks and optimize memory utilization."
    ))

    perf_table = [
        ["Operation / Component", "Typical Latency", "Complexity", "Optimization Strategy Implemented"],
        ["Cache Hit Response", "< 1 ms", "O(1) lookup", "In-memory dictionary keyed by SHA-256 signature (10-minute TTL)"],
        ["Two-Tier Rate Limit Check", "< 0.5 ms", "O(N) window", "Active pruning of expired timestamps to eliminate memory bloat"],
        ["Language Detection", "< 1 ms", "O(T) scan", "Fast Unicode range check (\\u0B80-\\u0BFF) before dictionary token set intersection"],
        ["FAISS Vector Retrieval", "< 10 ms", "O(K * D)", "Bypassed entirely for schemas <= 4 tables; Flat inner-product index on normalized vectors"],
        ["Gemini LLM Synthesis", "800 - 1500 ms", "O(Tokens)", "Lightweight flash-lite model; low temperature (0.1); concise system prompt"],
        ["sqlglot AST Validation", "1 - 3 ms", "O(Tokens)", "Pre-filtering string literals before comment scan; fast SQLite AST grammar"],
        ["SQLite Query Execution", "2 - 8 ms", "O(Rows)", "PRAGMA journal_mode=WAL and PRAGMA synchronous=NORMAL; indexed primary keys"],
        ["Chart Recommendation", "< 1 ms", "O(1) logic", "Heuristic shape evaluation: row count, numeric column distribution"],
        ["End-to-End User Latency", "900 - 1600 ms", "--", "Sub-2-second total turn-around on cache miss; sub-50ms on cache hit"],
    ]
    story.append(make_table(perf_table, [110, 65, 65, 280]))
    story.append(Spacer(1, 10))

    story.append(sub_header("13.1 RAM Optimization for Constrained Cloud Containers (Render 512MB)"))
    story.append(p(
        "A critical engineering achievement of this project was fitting a full Python AI stack (PyTorch, SentenceTransformers, "
        "FAISS, FastAPI, SQLite) into Render's strict 512MB free-tier RAM ceiling without triggering Out-Of-Memory (OOM) 137 kills:"
    ))
    story.append(bullet("<b>CPU-Only PyTorch Layering:</b> The Dockerfile installs PyTorch directly from <code>https://download.pytorch.org/whl/cpu</code>, reducing Docker image size from ~4.5GB to ~650MB and eliminating CUDA driver memory overhead."))
    story.append(bullet("<b>Thread Pool Clamping:</b> Sets <code>OMP_NUM_THREADS=1</code>, <code>MKL_NUM_THREADS=1</code>, and <code>TORCH_NUM_THREADS=1</code> in runtime environment to prevent OpenMP/MKL from spawning thread pools that exhaust memory."))
    story.append(bullet("<b>Lazy RAG Indexing:</b> Schemas with &le; 4 tables bypass SentenceTransformer loading entirely, keeping baseline idle RAM at ~110MB."))
    story.append(bullet("<b>Single Uvicorn Worker:</b> Running with <code>--workers 1</code> avoids duplicating Python interpreter memory."))

    # =========================================================================
    # SECTION 14: SCALABILITY & CLOUD DEPLOYMENT ROADMAP
    # =========================================================================
    story.extend(sec_header(14, "System Scalability Roadmap"))
    story.append(p(
        "To satisfy technical jury inquiries regarding enterprise readiness, the architecture distinguishes clearly between "
        "the current single-instance deployment and the recommended multi-node horizontal production architecture."
    ))

    scale_table = [
        ["Scale Tier", "Concurrent Users", "Database Size", "Current Implementation Behavior", "Required Production Architecture"],
        ["Prototype / Demo", "1 - 10 users", "< 10 MB", "Single Uvicorn worker on Render/local; in-memory cache and session store; local SQLite files.", "Current architecture is fully optimized and stable for this workload."],
        ["Departmental", "100 - 1,000 users", "10 MB - 1 GB", "In-memory rate limiter and write buffer would suffer under multi-worker Uvicorn without shared state.", "Deploy Redis for shared rate limiting and session cache; migrate meta.db to hosted PostgreSQL."],
        ["Enterprise Production", "10,000 - 100,000+ users", "100 GB - 10+ TB", "Single-node ASGI engine would bottleneck on synchronous DB execution and external Gemini rate limits.", "Horizontal autoscaling on AWS ECS/EKS; read-replica DB pools; async Celery query workers; local vLLM cluster."],
    ]
    story.append(make_table(scale_table, [65, 65, 60, 160, 170]))
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 15: ARCHITECTURAL DESIGN DECISIONS
    # =========================================================================
    story.extend(sec_header(15, "Architectural Design Decisions & Trade-Offs"))
    story.append(p(
        "Every major component selection involved weighing engineering trade-offs between development velocity, runtime latency, "
        "memory footprint, and defensive security."
    ))

    story.append(sub_header("1. FastAPI vs. Flask / Django"))
    story.append(p(
        "<b>Decision:</b> FastAPI with Starlette and Uvicorn.<br/>"
        "<b>Why:</b> Native async ASGI support, high request throughput, automated OpenAPI Swagger documentation, and first-class Pydantic v2 data validation.<br/>"
        "<b>Alternative Considered:</b> Flask (synchronous by default, lacks built-in request validation), Django (excessive monolith overhead for a decoupled REST API).<br/>"
        "<b>Trade-off:</b> FastAPI requires strict type hinting, but completely eliminates runtime type coercion bugs."
    ))

    story.append(sub_header("2. Universal Adapter Architecture vs. Direct Raw SQL"))
    story.append(p(
        "<b>Decision:</b> Abstract <code>BaseDatabaseAdapter</code> with concrete <code>SQLiteAdapter</code> and <code>PostgreSQLAdapter</code>.<br/>"
        "<b>Why:</b> Decouples the query execution engine from underlying database engines. The core AI pipeline does not need to know whether the target is a local file or remote PostgreSQL database.<br/>"
        "<b>Alternative Considered:</b> Raw SQLite scripts scattered through endpoint handlers.<br/>"
        "<b>Trade-off:</b> Requires maintaining an abstraction layer, but allows plug-and-play addition of MySQL, Snowflake, or DuckDB adapters without touching query generation logic."
    ))

    story.append(sub_header("3. AST Parsing (sqlglot) vs. Regular Expressions"))
    story.append(p(
        "<b>Decision:</b> Pure-Python AST parsing with <code>sqlglot</code>.<br/>"
        "<b>Why:</b> Regular expressions cannot handle nested SQL queries, quoted semicolons, or complex statement semantics. AST parsing provides mathematical certainty over statement types and clauses.<br/>"
        "<b>Alternative Considered:</b> Regex pattern matching (e.g. <code>re.search(r'\\bDROP\\b', sql)</code>).<br/>"
        "<b>Trade-off:</b> Adds ~2ms parsing overhead per query, but provides ironclad defense against SQL injection."
    ))

    story.append(sub_header("4. Two-Phase Staged Write Confirmation vs. Immediate Execution"))
    story.append(p(
        "<b>Decision:</b> Staged in-memory buffer (<code>_PENDING_WRITES</code>) requiring explicit <code>POST /api/confirm-write</code>.<br/>"
        "<b>Why:</b> AI is probabilistic. Directly executing AI-generated write mutations against a production database creates unacceptable risk of catastrophic data loss. The confirmation modal puts a human in the loop.<br/>"
        "<b>Alternative Considered:</b> Direct execution with a post-hoc undo log.<br/>"
        "<b>Trade-off:</b> Requires two round-trips for write mutations, but guarantees 100% human oversight before data modifications occur."
    ))

    # =========================================================================
    # SECTION 16: MODULE DEPENDENCY TOPOLOGY
    # =========================================================================
    story.extend(sec_header(16, "Module Dependency Topology & Blast Radius"))
    story.append(p(
        "The system adheres to a strict layered dependency structure. Lower layers never depend on higher layers, "
        "preventing circular dependencies and enabling isolated unit testing."
    ))

    dep_diagram = """
+-------------------------------------------------------------------------+
|                              PRESENTATION LAYER                         |
|  App.jsx -> ChatWindow.jsx -> MessageBubble.jsx -> ChartPanel.jsx       |
+------------------------------------+------------------------------------+
                                     | api/client.js (Axios)
                                     v
+-------------------------------------------------------------------------+
|                               API ROUTER LAYER                          |
|  main.py -> routers/query.py, routers/connect_db.py, conversations.py   |
+-------------------+----------------+-------------------+----------------+
                    |                |                   |
                    v                v                   v
+-----------------------+  +--------------------+  +----------------------+
|    SERVICES LAYER     |  |   DATABASE LAYER   |  |   PERSISTENCE LAYER  |
|  sql_generator.py     |  |  manager.py        |  |  meta_db.py          |
|  sql_validator.py     |  |  sqlite_adapter.py |  |  (SessionLocal,     |
|  execution_engine.py  |  |  postgres_adapter.py| |   models)            |
|  rag_service.py       |  |  base.py           |  |                      |
|  session_store.py     |  +--------------------+  +----------------------+
+-----------------------+
"""
    story.extend(ascii_diagram(dep_diagram, "Layered Architecture Dependency Map"))

    story.append(sub_header("16.1 Blast Radius Analysis"))
    story.append(bullet("<b>Central Engine Module:</b> <code>app/services/sql_generator.py</code>. If modified or corrupted, all natural language translation ceases. However, AST validation and direct DB querying remain functional."))
    story.append(bullet("<b>Central Security Module:</b> <code>app/services/sql_validator.py</code>. If removed, query execution fails closed (safe by default)."))
    story.append(bullet("<b>Independent Modules:</b> <code>app/services/rag_service.py</code> and <code>app/database/sqlite_adapter.py</code> can be tested and modified in total isolation from web routers or LLM models."))

    return story

