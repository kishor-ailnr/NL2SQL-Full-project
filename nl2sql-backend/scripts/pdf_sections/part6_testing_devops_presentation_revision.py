"""Part 6: Sections 21 through 28
- SECTION 21: Verification & Testing Matrix (166 Test Cases, 100% Pass)
- SECTION 22: Deployment, Containerization & DevOps Pipeline
- SECTION 23: Technical Weaknesses, Risks & Production Remediation
- SECTION 24: 5-Minute Technical Presentation Delivery Script
- SECTION 25: 30-Second Technical Elevator Pitch
- SECTION 26: 2-Minute Architectural Executive Briefing
- SECTION 27: Rapid 10-Minute Pre-Jury Revision Sheet
- SECTION 28: Exhaustive Technical Glossary
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


def build_part6():
    story = []

    # =========================================================================
    # SECTION 21: TESTING & VERIFICATION MATRIX
    # =========================================================================
    story.extend(sec_header(21, "Verification & Testing Matrix"))
    story.append(p(
        "The NL2SQL backend undergoes rigorous automated quality assurance via <code>pytest</code>, <code>pytest-cov</code>, "
        "and Starlette's <code>TestClient</code>. The entire suite consists of <b>166 automated test cases</b> across 17 test modules, "
        "achieving a <b>100% pass rate</b>."
    ))

    test_matrix = [
        ["Test Module", "Target Subsystem", "Test Classes / Focus Areas", "Tests Count", "Pass Rate"],
        ["test_sql_validator.py", "AST Security Gate", "Valid SELECTs, comment stripping, DDL blocks, WHERE clauses", "44 tests", "100% PASS"],
        ["test_security.py", "API Gateway & Security", "Security headers, file upload guards, two-tier rate limiting", "23 tests", "100% PASS"],
        ["test_conversations.py", "Thread Persistence", "CRUD operations, Turn isolation, Follow-up context queries", "16 tests", "100% PASS"],
        ["test_adapters_and_writes.py", "DB Adapters & Writes", "SQLite/Postgres adapters, schema extraction, confirm-write", "7 tests", "100% PASS"],
        ["test_execution_engine.py", "Execution Engine", "Safe SELECT execution, path leak masking, duplicate checks", "11 tests", "100% PASS"],
        ["test_rag.py", "FAISS RAG Service", "Small schema bypass, large schema retrieval, embedding lifecycle", "11 tests", "100% PASS"],
        ["test_clarification.py", "Ambiguity Engine", "Underspecified queries, unconstrained ranking terms ('top')", "10 tests", "100% PASS"],
        ["test_multilingual.py", "Multilingual NLP", "Tamil script Unicode, Thanglish vocabulary, translation fallback", "9 tests", "100% PASS"],
        ["test_voice_correction.py", "Phonetic Correction", "Levenshtein distance, near-miss speech correction", "9 tests", "100% PASS"],
        ["test_data_value_integrity.py", "Data Availability", "Out-of-schema entity detection, schema boundaries", "8 tests", "100% PASS"],
        ["test_self_correction.py", "Self-Correction Loop", "Iterative syntax repair, execution error healing (3 attempts)", "8 tests", "100% PASS"],
        ["test_connection.py", "DB Connection", "Demo hospital/ecommerce connect, schema introspection", "7 tests", "100% PASS"],
        ["test_health.py", "Liveness Probe", "HTTP /health status, content-type verification", "3 tests", "100% PASS"],
    ]
    story.append(make_table(test_matrix, [125, 105, 170, 60, 60]))
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 22: DEPLOYMENT & DEVOPS PIPELINE
    # =========================================================================
    story.extend(sec_header(22, "Deployment, Containerization & DevOps Pipeline"))
    story.append(p(
        "NL2SQL implements a unified deployment model where pre-built React frontend assets are served directly "
        "by FastAPI from its static root, eliminating cross-origin CORS overhead in production."
    ))

    story.append(sub_header("22.1 Multi-Stage Dockerfile Architecture"))
    story.append(bullet("<b>Stage 1 (Frontend Builder):</b> Uses <code>node:20-alpine</code>. Installs dependencies via <code>npm ci</code> and compiles production assets with <code>npm run build</code> into <code>/frontend/dist</code>. The API base URL defaults to same-origin (<code>VITE_API_BASE_URL=''</code>)."))
    story.append(bullet("<b>Stage 2 (Runtime Container):</b> Uses <code>python:3.11-slim</code>. Installs CPU-only PyTorch via <code>--index-url https://download.pytorch.org/whl/cpu</code>, reducing image size by ~3.5GB. Copies backend application code and compiled frontend assets."))
    story.append(bullet("<b>Thread Clamping:</b> Sets <code>OMP_NUM_THREADS=1</code>, <code>MKL_NUM_THREADS=1</code>, and <code>TORCH_NUM_THREADS=1</code> to prevent multithreaded math libraries from blowing through RAM limits."))
    story.append(bullet("<b>Healthcheck & Cold Start:</b> Defines a Docker HEALTHCHECK polling <code>http://localhost:8000/health</code> with a <code>start-period=60s</code> grace window, preventing premature container terminations on slow cloud cold-starts."))

    # =========================================================================
    # SECTION 23: TECHNICAL WEAKNESSES & RISKS
    # =========================================================================
    story.extend(sec_header(23, "Technical Weaknesses, Risks & Production Remediation"))
    story.append(p(
        "In accordance with rigorous software engineering ethics, this audit outlines the system's operational boundaries "
        "and provides concrete remediation strategies for enterprise scale."
    ))

    risk_table = [
        ["Identified Weakness / Risk", "Root Cause in Current Implementation", "Operational Impact", "Production Remediation Strategy"],
        ["In-Memory Rate Limiting", "Timestamps stored in local dict (_QUERY_TIMESTAMPS)", "Rate limit counts reset on restart; does not scale across multiple Uvicorn worker processes.", "Replace in-memory dictionary with a distributed Redis sliding-window counter using Redis EVAL scripts."],
        ["In-Memory Write Buffer", "Staged mutations stored in _PENDING_WRITES buffer", "Unconfirmed write operations are lost if server restarts before user clicks confirm.", "Persist staged writes to meta.db in a 'pending_writes' table with a 5-minute expiration timestamp."],
        ["Web Speech API Dependency", "Relies on browser-native SpeechRecognition interface", "Voice transcription is limited to Chromium browsers (Chrome, Edge); unavailable in Firefox.", "Integrate an optional server-side Whisper API audio upload endpoint for universal browser support."],
        ["Synchronous DB Drivers", "sqlite3 and psycopg2 use blocking I/O calls", "Long-running queries can block the single-worker ASGI event loop temporarily.", "Migrate adapter implementations to asynchronous drivers: aiosqlite for SQLite and asyncpg for PostgreSQL."],
        ["PostgreSQL Driver Bundling", "psycopg2-binary is optional to conserve image size", "Connecting to live PostgreSQL requires ensuring driver is installed in Python environment.", "Package asyncpg in core requirements.txt once container memory limits permit expanded baseline footprint."],
    ]
    story.append(make_table(risk_table, [105, 110, 135, 170]))
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 24: 5-MINUTE TECHNICAL PRESENTATION SCRIPT
    # =========================================================================
    story.extend(sec_header(24, "5-Minute Technical Presentation Delivery Script"))
    story.append(p(
        "Follow this exact timed structure during your five-minute technical presentation before the jury:"
    ))
    story.append(bullet("<b>0:00 - 0:30 &mdash; The Problem:</b> 'Good morning, esteemed jury. Today, relational databases power enterprise operations, yet 80% of business stakeholders cannot extract insights without burdening data engineering teams. Furthermore, naive LLMs hallucinate schema details, risk SQL injection, and lack regional language support.'"))
    story.append(bullet("<b>0:30 - 1:00 &mdash; The Solution:</b> 'We built NL2SQL: an enterprise conversational query engine supporting English, native Tamil script, and Thanglish. It guarantees mathematical query safety through AST validation, stages write mutations for human confirmation, and dynamically renders Chart.js visualizations.'"))
    story.append(bullet("<b>1:00 - 2:00 &mdash; Architecture & Innovation:</b> 'Our architecture decouples a React Vite frontend from a FastAPI ASGI backend. Queries pass through six defensive gates: rate limiting, language/phonetic normalization, schema-aware FAISS vector RAG, Gemini Flash-Lite synthesis, sqlglot AST parsing, and an autonomous self-correction loop that heals syntax errors up to three times.'"))
    story.append(bullet("<b>2:00 - 3:30 &mdash; Deep Technical Implementation:</b> 'Notice our universal database abstraction: BaseDatabaseAdapter allows live SQLite, PostgreSQL, or CSV/SQL uploads to be queried identically. For write safety, SELECT queries run immediately, while INSERT, UPDATE, and DELETE operations are staged in memory with session ownership authorization. Transactions commit atomically or roll back completely.'"))
    story.append(bullet("<b>3:30 - 4:30 &mdash; Live Demonstration:</b> [Demonstrate connecting hospital DB &rarr; ask in Thanglish 'Cardiology doctor yaaru' &rarr; inspect generated SQL &rarr; show ChartPanel visualization &rarr; demonstrate typing write query & ConfirmModal.]"))
    story.append(bullet("<b>4:30 - 5:00 &mdash; Verification & Roadmap:</b> 'Our codebase is proven with 166 automated test cases at 100% pass rate. It is containerized via multi-stage Docker and optimized for 512MB RAM cloud hosting. We are ready for your technical questions.'"))

    # =========================================================================
    # SECTION 25: 30-SECOND TECHNICAL ELEVATOR PITCH
    # =========================================================================
    story.extend(sec_header(25, "30-Second Technical Elevator Pitch"))
    story.append(callout(
        "&ldquo;NL2SQL is an enterprise conversational AI query system that translates natural language—in English, "
        "Tamil, and Thanglish—into verified, production-safe SQL across SQLite and PostgreSQL databases. "
        "Unlike naive LLM wrappers, we enforce a strict defense-in-depth pipeline: schema-aware FAISS vector RAG, "
        "mathematical AST validation via sqlglot, two-phase staged write confirmations, and an autonomous self-correction retry loop. "
        "Verified with 166 automated test cases, the system delivers sub-second deterministic responses, zero-row result reasoning, "
        "and automated Chart.js visualizations.&rdquo;",
        title="VERBAL DEFENSE: 30-SECOND ELEVATOR PITCH",
        border_color=C_TEAL,
        bg_color=C_BG_CARD,
    ))

    # =========================================================================
    # SECTION 26: 2-MINUTE ARCHITECTURAL EXECUTIVE BRIEFING
    # =========================================================================
    story.extend(sec_header(26, "2-Minute Architectural Executive Briefing"))
    story.append(p(
        "When granted two minutes to provide a deeper technical summary, deliver the following structured brief:"
    ))
    story.append(bullet("<b>System Topology:</b> 'Our system is architected as an asynchronous, decoupled client-server application. The client is a React 18 SPA built with Vite, TailwindCSS, Chart.js, and browser-native Web Speech API. The backend is powered by Python 3.11 and FastAPI over Uvicorn, implementing security headers, sliding-window rate limiting, and session-isolated database adapters.'"))
    story.append(bullet("<b>AI Pipeline & Schema Grounding:</b> 'We use Google Gemini Flash-Lite configured at temperature 0.1 for deterministic synthesis. To handle enterprise schemas without token bloat, our schema-aware RAG embeds table definitions using SentenceTransformers (all-MiniLM-L6-v2) into a FAISS IndexFlatIP vector index, dynamically retrieving the top-4 relevant tables for schemas larger than 4 tables. Schemas under 4 tables bypass RAG to conserve RAM.'"))
    story.append(bullet("<b>Defensive Security & Validation:</b> 'Security is enforced through sqlglot AST parsing. We pre-strip string literals to block SQL comment bypasses, unconditionally reject destructive DDL commands, and require explicit WHERE clauses on all UPDATE and DELETE statements. Write operations are never executed directly; they are staged in memory with strict session ownership verification, requiring explicit two-phase confirmation.'"))
    story.append(bullet("<b>Resilience & Performance:</b> 'If an LLM syntax error occurs, our self-correction loop catches the database exception and passes the failure context back to Gemini to heal the query across up to 3 attempts. Query responses are cached with a deterministic SHA-256 signature and a 10-minute TTL, automatically invalidated upon confirmed data mutations. The entire system is proven with 166 automated pytest cases passing at 100%.'"))

    # =========================================================================
    # SECTION 27: RAPID 10-MINUTE REVISION SHEET
    # =========================================================================
    story.extend(sec_header(27, "Rapid 10-Minute Pre-Jury Revision Sheet"))
    story.append(p(
        "Review these key facts, file mappings, algorithms, and numbers immediately before entering your technical defense:"
    ))

    rev_data = [
        ["Metric / Concept", "Exact Code Value / Configuration", "Architectural Reference"],
        ["Test Suite Results", "166 Passed, 0 Failed, 0 Skipped (100% Pass)", "TEST_REPORT.md | tests/conftest.py"],
        ["Rate Limiting Limits", "20 req/min per session; 100 req/min global", "app/routers/query.py: check_rate_limit()"],
        ["Response Cache TTL", "600 seconds (10 minutes) with write invalidation", "app/services/sql_generator.py: _QUERY_CACHE"],
        ["Self-Correction Retries", "Up to 2 retries (original attempt + 2 retries = 3 attempts)", "app/routers/query.py: MAX_RETRIES = 2"],
        ["RAG Threshold", "Bypassed for <= 4 tables; top-4 retrieval for > 4 tables", "app/services/rag_service.py: retrieve_relevant_tables()"],
        ["Embedding Dimension", "384-dimensional dense vectors (all-MiniLM-L6-v2)", "app/services/rag_service.py: IndexFlatIP"],
        ["Gemini Model", "gemini-3.1-flash-lite at temperature = 0.1", "app/services/sql_generator.py: MODELS_TO_TRY"],
        ["AST Parser", "sqlglot (pure Python AST parsing & transpilation)", "app/services/sql_validator.py: validate_sql()"],
        ["SQLite Pragma Mode", "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL", "app/models/meta_db.py: set_sqlite_pragma()"],
        ["Write Buffer Key", "_PENDING_WRITES dictionary keyed by query_id", "app/routers/query.py: _PENDING_WRITES"],
        ["File Upload Ceiling", "5MB maximum; whitelisted to .csv and .sql extensions", "app/routers/connect_db.py: upload_data()"],
        ["Tamil Unicode Range", "\\u0B80 through \\u0BFF character block", "app/services/sql_generator.py: detect_input_language()"],
    ]
    story.append(make_table(rev_data, [130, 210, 180]))
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 28: TECHNICAL GLOSSARY
    # =========================================================================
    story.extend(sec_header(28, "Exhaustive Technical Glossary"))
    story.append(p(
        "Authoritative definitions for all advanced software engineering and AI terms utilized in the codebase:"
    ))
    story.append(bullet("<b>Abstract Syntax Tree (AST):</b> A tree representation of the abstract syntactic structure of source code or SQL statements, where each node denotes a construct (e.g. <code>exp.Select</code>, <code>exp.Where</code>)."))
    story.append(bullet("<b>Retrieval-Augmented Generation (RAG):</b> An AI architecture that retrieves external knowledge (such as database schemas) using vector similarity search to ground LLM generation and eliminate hallucinations."))
    story.append(bullet("<b>Cosine Similarity:</b> A mathematical measure of similarity between two non-zero vectors calculating the cosine of the angle between them, evaluated as their normalized dot product."))
    story.append(bullet("<b>FAISS (Facebook AI Similarity Search):</b> A high-performance library for efficient similarity search and dense vector clustering."))
    story.append(bullet("<b>Write-Ahead Logging (WAL):</b> A database transaction logging technique where modifications are written to a separate WAL file before being applied to the database, enabling concurrent reads during writes."))
    story.append(bullet("<b>Two-Phase Confirmation:</b> A safety design pattern where destructive operations are first parsed, validated, and staged in memory, requiring an explicit second affirmative request before execution."))
    story.append(bullet("<b>Sliding Window Counter:</b> A rate limiting algorithm tracking individual request timestamps within a moving time window (60s) to enforce smooth, burst-resistant request limits."))
    story.append(bullet("<b>Content Security Policy (CSP):</b> An HTTP response header restricting the sources from which scripts, styles, fonts, and frames may be loaded by the browser, mitigating XSS and clickjacking."))
    story.append(bullet("<b>Deterministic Caching:</b> Hashing query inputs and schema state via cryptographic SHA-256 to ensure identical inputs always map to identical cache slots without non-deterministic key drift."))

    return story

