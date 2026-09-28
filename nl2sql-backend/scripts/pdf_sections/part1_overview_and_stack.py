"""Part 1: Sections 1 through 4
- SECTION 1: Project Overview & Architecture
- SECTION 2: Complete Technology Stack & In-Depth Analysis
- SECTION 3: Complete Project Folder Structure
- SECTION 4: Complete File/Module Inventory & Responsibilities
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


def build_part1():
    story = []

    # =========================================================================
    # COVER / HEADER BLOCK
    # =========================================================================
    story.append(Paragraph("NL2SQL: PRODUCTION CONVERSATIONAL AI NATURAL LANGUAGE TO SQL SYSTEM", STYLES["DocTitle"]))
    story.append(Paragraph("Comprehensive Technical Project Analysis, Software Architecture Audit & Technical Jury Defense Guide", STYLES["DocSubtitle"]))

    meta_table_data = [
        [
            Paragraph("<b>Target Audience:</b>", STYLES["MetaLabel"]),
            Paragraph("Software Engineering, AI/ML & System Architecture Jury Panel", STYLES["MetaValue"]),
            Paragraph("<b>Architecture Pattern:</b>", STYLES["MetaLabel"]),
            Paragraph("Decoupled SPA + REST API + Universal DB Abstraction", STYLES["MetaValue"]),
        ],
        [
            Paragraph("<b>Core AI Engine:</b>", STYLES["MetaLabel"]),
            Paragraph("Google Gemini (Flash-Lite) + SentenceTransformer + FAISS", STYLES["MetaValue"]),
            Paragraph("<b>Validation Engine:</b>", STYLES["MetaLabel"]),
            Paragraph("sqlglot AST Engine + Staged Write State Machine", STYLES["MetaValue"]),
        ],
        [
            Paragraph("<b>Multilingual Scope:</b>", STYLES["MetaLabel"]),
            Paragraph("English, Tamil Script (Unicode), Thanglish (Phonetic)", STYLES["MetaValue"]),
            Paragraph("<b>Verification Status:</b>", STYLES["MetaLabel"]),
            Paragraph("166 Automated Test Cases Passed (100% Pass Rate)", STYLES["MetaValue"]),
        ],
    ]
    t_meta = Table(meta_table_data, colWidths=[90, 170, 110, 150])
    t_meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.75, C_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 12))

    # =========================================================================
    # EXECUTIVE TABLE OF CONTENTS
    # =========================================================================
    story.append(sub_header("Document Organization & Table of Contents"))
    toc_data = [
        ["Sec 1: Project Overview & System Topology", "Sec 11: Comprehensive Security Architecture", "Sec 21: Verification & Testing Matrix"],
        ["Sec 2: Complete Technology Stack Audit", "Sec 12: Error Handling & Fault Tolerance", "Sec 22: Deployment & Containerization"],
        ["Sec 3: Project Directory Hierarchy", "Sec 13: Latency & Performance Profile", "Sec 23: Technical Weaknesses & Risks"],
        ["Sec 4: File & Module Inventory Sheet", "Sec 14: System Scalability Roadmap", "Sec 24: 5-Minute Technical Presentation"],
        ["Sec 5: Deep Source Code Inspection", "Sec 15: Architectural Design Trade-Offs", "Sec 25: 30-Second Technical Pitch"],
        ["Sec 6: Critical Code Block Analysis", "Sec 16: Module Dependency Topology", "Sec 26: 2-Minute Architectural Briefing"],
        ["Sec 7: Complete End-to-End Data Flows", "Sec 17: Jury Must-Know Core Concepts", "Sec 27: Rapid 10-Minute Revision Sheet"],
        ["Sec 8: RESTful API Endpoint Audit", "Sec 18: Technical Jury Question Bank (A-R)", "Sec 28: Exhaustive Technical Glossary"],
        ["Sec 9: Relational Schema & Storage Design", "Sec 19: Adversarial Jury Cross-Questions", ""],
        ["Sec 10: AI, LLM, RAG & Multilingual Engine", "Sec 20: 'Show Me The Code' Walkthroughs", ""],
    ]
    story.append(make_table(toc_data, [173, 173, 174], has_header=False))
    story.append(Spacer(1, 14))

    # =========================================================================
    # SECTION 1: PROJECT OVERVIEW
    # =========================================================================
    story.extend(sec_header(1, "Project Overview"))
    story.append(sub_header("1.1 Project Identity & Executive Summary"))
    story.append(p(
        "<b>NL2SQL</b> is an enterprise-grade, conversational Natural Language-to-SQL (NL2SQL) system engineered to empower "
        "non-technical domain users—such as hospital administrators, retail inventory managers, business analysts, and executives—to "
        "interrogate and safely manipulate relational databases without writing SQL syntax. Users interact via text or voice "
        "in <b>English, Tamil script</b>, or <b>Thanglish</b> (Tamil phonetic transliteration in Latin script). The system returns "
        "syntactically verified SQL, natural language explanations, automated Chart.js visualizations, and an educational "
        "'Learn SQL' interactive breakdown."
    ))

    story.append(sub_header("1.2 The Problem Being Solved"))
    story.append(p(
        "Enterprise relational databases remain siloed behind the technical barrier of SQL. While non-technical staff require daily "
        "data insights, conventional approaches suffer from severe operational friction:"
    ))
    story.append(bullet("<b>Developer Bottleneck:</b> Business analysts and operators must request ad-hoc SQL reports from engineering teams, introducing delays of hours or days."))
    story.append(bullet("<b>Hallucination & Syntax Failures in Naive LLMs:</b> Generic LLMs frequently hallucinate non-existent table and column names, omit necessary JOIN conditions, or produce dialect-incompatible syntax."))
    story.append(bullet("<b>Catastrophic Data Loss & Security Risks:</b> Connecting LLMs directly to databases exposes systems to SQL injection, accidental DROP/TRUNCATE execution, and unconstrained UPDATE/DELETE mutations without WHERE clauses."))
    story.append(bullet("<b>Linguistic Exclusivity:</b> Most NL2SQL systems operate exclusively in English, isolating regional domain workers in diverse linguistic settings such as Tamil Nadu, India."))

    story.append(sub_header("1.3 Target Users"))
    story.append(bullet("<b>Clinical & Operational Hospital Staff:</b> Doctors and administrators querying patient admissions, doctor assignments, and billing without technical assistance."))
    story.append(bullet("<b>E-Commerce & Retail Merchants:</b> Store operators monitoring customer orders, inventory stock levels, category sales, and product performance."))
    story.append(bullet("<b>Business & Financial Analysts:</b> Professionals requiring instant statistical summaries, KPI cards, and trend visualizations from connected SQLite or PostgreSQL databases."))
    story.append(bullet("<b>Engineering Teams & Students:</b> Developers and learners utilizing the pedagogical 'Learn SQL' engine to understand relational query construction block-by-block."))

    story.append(sub_header("1.4 Main Objectives & Key Architectural Features"))
    story.append(p(
        "The system satisfies four primary technical objectives: <b>Correctness</b>, <b>Safety</b>, <b>Accessibility</b>, and <b>Observability</b>. "
        "Key capabilities implemented in the codebase include:"
    ))
    story.append(bullet("<b>Universal Database Support:</b> An object-oriented adapter architecture (<code>BaseDatabaseAdapter</code>) managing live SQLite files, PostgreSQL network endpoints, and uploaded CSV/SQL files."))
    story.append(bullet("<b>Deep Schema & Constraint Introspection:</b> Automated extraction of table structures, primary keys, foreign keys, nullability, row counts, and distinct non-leaking sample values."))
    story.append(bullet("<b>Schema-Aware Vector RAG (FAISS + all-MiniLM-L6-v2):</b> Vector similarity retrieval dynamically trimming large database schemas (> 4 tables) to the top relevant tables, avoiding LLM prompt bloat while preserving small schemas intact."))
    story.append(bullet("<b>Trilingual NLP Engine:</b> Deterministic language detection and prompt grounding for English, native Tamil script (Unicode block <code>\\u0B80-\\u0BFF</code>), and Thanglish."))
    story.append(bullet("<b>Phonetic Speech Normalization:</b> Browser-native Web Speech API capture paired with backend phonetic mishearing correction (e.g. 'pashents' &rarr; 'patients')."))
    story.append(bullet("<b>Ambiguity & Boundary Pre-Checks:</b> Pre-generation interception for unconstrained ranking terms ('top patients') and out-of-schema entities (asking for flights on a hospital DB)."))
    story.append(bullet("<b>Hardened AST Validation (sqlglot):</b> Strict Abstract Syntax Tree parsing rejecting multi-statement injection, comments, destructive DDL (DROP, ALTER, TRUNCATE), and unconstrained writes."))
    story.append(bullet("<b>Guarded Two-Phase Write Confirmation:</b> Strict READ-ONLY default; write operations (INSERT, UPDATE, DELETE) are staged in memory (<code>_PENDING_WRITES</code>) and executed only upon explicit user confirmation."))
    story.append(bullet("<b>Autonomous Self-Correction Loop:</b> Automated retry mechanism (up to 3 attempts) passing validation or database execution syntax errors back to Gemini for real-time query repair."))
    story.append(bullet("<b>In-Memory Deterministic Caching:</b> SHA-256 hashed response cache with 10-minute TTL, automatically invalidated upon confirmed write modifications."))
    story.append(bullet("<b>Zero-Result Reasoning Engine:</b> Evaluates empty dataset results against schema sample values to explain <i>why</i> zero rows were returned."))

    story.append(sub_header("1.5 High-Level Architectural Diagram"))
    arch_diagram = """
+-----------------------------------------------------------------------------------------+
|                                    CLIENT LAYER                                         |
|  React 18 + Vite SPA | Web Speech API | Chart.js 4.4 | Lucide Icons | Axios HTTP        |
+--------------------------------------------+--------------------------------------------+
                                             | HTTP REST (JSON / Multipart)
                                             v
+-----------------------------------------------------------------------------------------+
|                              API GATEWAY & MIDDLEWARE LAYER                             |
|  SecurityHeadersMiddleware (CSP, nosniff, DENY) | Sliding-Window Rate Limiter (20/100)  |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                   CORE AI PIPELINE                                      |
|  1. Language & Phonetic Detection (Unicode / Thanglish dictionary / Levenshtein)       |
|  2. Schema-Aware Vector RAG (SentenceTransformer all-MiniLM-L6-v2 + FAISS IndexFlatIP) |
|  3. Data Availability & Ambiguity Verification Engine (Pre-generation Gate)             |
|  4. Contextual Prompt Assembly & Gemini LLM Synthesis (gemini-3.1-flash-lite)          |
|  5. AST SQL Safety Gate (sqlglot AST parse / multi-statement & DDL rejection)          |
|  6. Autonomous Self-Correction Loop (Up to 3 retries on validation/execution failure)   |
|  7. In-Memory Response Caching (SHA-256 signature / 10-min TTL / Write invalidation)   |
+--------------------------------------------+--------------------------------------------+
                                             |
                      +----------------------+----------------------+
                      | (SELECT Query)                              | (INSERT/UPDATE/DELETE)
                      v                                             v
+---------------------------------------------+   +---------------------------------------+
|        EXECUTION ENGINE (READ PATH)         |   |     STAGED CONFIRMATION (WRITE PATH)  |
|  run_select() -> Adapter execute_query()    |   |  Staged in _PENDING_WRITES buffer     |
|  Zero-row result reasoning generator        |   |  Returned as query_type: 'write'      |
|  Automatic Chart Recommendation (ChartPanel)|   |  User review in ConfirmModal.jsx      |
+---------------------+-----------------------+   |  POST /api/confirm-write execution    |
                      |                           +-------------------+-------------------+
                      +----------------------+------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                           UNIVERSAL DATABASE ADAPTER LAYER                              |
|  DatabaseConnectionManager (Registry & Factory keyed by session_id)                     |
|  +---------------------------------------+  +----------------------------------------+  |
|  | SQLiteAdapter                         |  | PostgreSQLAdapter                      |  |
|  | PRAGMA introspection, WAL mode,       |  | SQLAlchemy Engine, information_schema, |  |
|  | Duplicate INSERT check, Path sanitize |  | Live connection ping, Driver verify    |  |
|  +---------------------------------------+  +----------------------------------------+  |
+--------------------------------------------+--------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                   PERSISTENCE LAYER                                     |
|  - meta.db: sessions, conversations, query_history (PRAGMA journal_mode=WAL)            |
|  - Target Databases: demo_hospital.db, demo_ecommerce.db, uploaded CSV/SQL databases   |
+-----------------------------------------------------------------------------------------+
"""
    story.extend(ascii_diagram(arch_diagram, "End-to-End System Topology & Interaction Flow"))

    # =========================================================================
    # SECTION 2: COMPLETE TECHNOLOGY STACK
    # =========================================================================
    story.extend(sec_header(2, "Complete Technology Stack"))
    story.append(p(
        "Every technology in the codebase was deliberately selected to fulfill specific architectural guarantees: "
        "type safety, low latency, robust AST manipulation, mathematical semantic search, and defensive security."
    ))

    stack_table = [
        ["Layer", "Technology", "Version", "Exact Purpose in Project", "Architectural Rationale"],
        ["Frontend UI", "React.js", "18.3.1", "SPA component hierarchy and state management", "Declarative rendering, reactive state for chat streams and modals."],
        ["Frontend Build", "Vite", "5.4.2", "Development server and asset bundler", "Near-instant HMR, ES module bundling, content-hashed asset production."],
        ["Styling", "Tailwind CSS", "3.4.1", "Utility-first responsive design system", "Eliminates CSS bloat via PurgeCSS; consistent slate/teal dark/light palette."],
        ["Icons", "Lucide React", "0.344.0", "UI vector iconography", "Tree-shakable SVG icon set with zero runtime overhead."],
        ["Visualization", "Chart.js / react-chartjs-2", "4.4.8 / 5.3.0", "Dynamic data chart rendering", "HTML5 Canvas rendering of bar charts, line graphs, and KPI cards."],
        ["Speech Input", "Web Speech API", "Browser Native", "Speech-to-text audio capture", "Zero-latency in-browser transcription without costly cloud audio API calls."],
        ["HTTP Client", "Axios", "1.7.9", "REST communication with FastAPI backend", "Interceptors, unified error normalization, configurable base URLs."],
        ["Backend Web", "FastAPI", "0.139.0", "Asynchronous ASGI API gateway", "High-throughput ASGI server, automatic OpenAPI docs, Pydantic schema validation."],
        ["Server Engine", "Uvicorn", "0.51.0", "ASGI HTTP server implementation", "Production ASGI worker handling HTTP/1.1 and WebSockets efficiently."],
        ["Validation", "Pydantic", "2.13.4", "Data parsing and contract enforcement", "Type validation, serialization, and automatic schema documentation."],
        ["Middleware", "Starlette", "1.3.1", "HTTP kernel, security headers, CORS", "Lightweight HTTP primitives, CORS middleware, base middleware dispatch."],
        ["Primary AI LLM", "Google Gemini API", "google-genai", "NL to SQL synthesis & explanation", "Large context window, high reasoning speed, native JSON schema mode."],
        ["Embeddings", "SentenceTransformers", "3.0+", "Semantic dense vector generation", "Local 384-dimensional vector embeddings via all-MiniLM-L6-v2."],
        ["Vector Search", "FAISS", "faiss-cpu", "Schema-aware similarity retrieval", "Millisecond cosine similarity search over table schema representations."],
        ["SQL Parsing", "sqlglot", "25.0+", "AST SQL validation & comment removal", "Dialect-aware AST construction, statement isolation, syntax checking."],
        ["Relational DB", "SQLite3", "3.45+", "Metadata store & demo databases", "Zero-configuration serverless ACID relational storage with WAL mode."],
        ["Enterprise DB", "PostgreSQL / SQLAlchemy", "2.0.51", "Enterprise database adapter & ORM", "Universal connection interface, information_schema introspection."],
        ["Containerization", "Docker", "Multi-stage", "Unified build and runtime deployment", "Two-stage build: Node 20 asset bundling + Python 3.11 slim runtime."],
        ["Testing Engine", "pytest / pytest-cov", "9.1.1 / 7.1.0", "Automated test suite & coverage", "Parametric test suites, Starlette TestClient integration, coverage metrics."],
    ]
    story.append(make_table(stack_table, [65, 80, 45, 165, 165]))
    story.append(Spacer(1, 10))

    story.append(sub_header("2.1 In-Depth Analysis of Critical Technologies"))

    story.append(sub_sub_header("1. Google Gemini API (gemini-3.1-flash-lite)"))
    story.append(p(
        "<b>What it is:</b> Google's state-of-the-art lightweight generative language model.<br/>"
        "<b>Where used:</b> <code>app/services/sql_generator.py</code> in <code>generate_sql()</code> and <code>regenerate_sql()</code>.<br/>"
        "<b>Why used:</b> Offers sub-second inference latency, robust multilingual understanding (native Tamil script and Thanglish), "
        "and strict adherence to JSON output schemas.<br/>"
        "<b>What happens if removed:</b> Natural language query synthesis halts. The system would require replacing it with an alternative "
        "LLM client (e.g. OpenAI GPT-4o or a local Ollama model).<br/>"
        "<b>Alternatives:</b> OpenAI GPT-4o-mini, Anthropic Claude 3.5 Haiku, local CodeLlama 13B via vLLM.<br/>"
        "<b>Key Concepts:</b> System instructions, temperature (set to 0.1 for deterministic SQL), JSON mode, few-shot prompt grounding."
    ))

    story.append(sub_sub_header("2. sqlglot (AST Parsing & SQL Transpilation Engine)"))
    story.append(p(
        "<b>What it is:</b> A pure-Python SQL parser, transpiler, and Abstract Syntax Tree (AST) analyzer.<br/>"
        "<b>Where used:</b> <code>app/services/sql_validator.py</code> and <code>app/services/execution_engine.py</code>.<br/>"
        "<b>Why used:</b> Regular expressions are fundamentally incapable of validating recursive SQL grammars. <code>sqlglot</code> parses "
        "statements into mathematical AST trees, identifying individual expressions (<code>exp.Select</code>, <code>exp.Insert</code>, <code>exp.Update</code>, <code>exp.Drop</code>), "
        "detecting stacked queries separated by semicolons, and validating required clauses like <code>WHERE</code>.<br/>"
        "<b>What happens if removed:</b> The system would lose its primary security defense, exposing the database to SQL injection bypasses, "
        "stacked destructive commands, and unconstrained table updates.<br/>"
        "<b>Alternatives:</b> <code>sqlparse</code> (token-based only, cannot build semantic AST), <code>pglast</code> (PostgreSQL only, C dependency).<br/>"
        "<b>Key Concepts:</b> Abstract Syntax Tree, expression traversal (<code>stmt.find(exp.Where)</code>), dialect normalization."
    ))

    story.append(sub_sub_header("3. SentenceTransformers ('all-MiniLM-L6-v2') & FAISS"))
    story.append(p(
        "<b>What it is:</b> A pre-trained bi-encoder neural network mapping text to 384-dimensional dense vectors, paired with Facebook AI Similarity Search.<br/>"
        "<b>Where used:</b> <code>app/services/rag_service.py</code>.<br/>"
        "<b>Why used:</b> When a database contains dozens or hundreds of tables, feeding the entire schema into an LLM prompt exhausts context limits, "
        "degrades reasoning accuracy, and skyrockets latency. FAISS indexes table metadata summaries and retrieves only the top-4 relevant tables.<br/>"
        "<b>What happens if removed:</b> For large schemas, prompt token count explodes, increasing API cost and latency by up to 400%, and confusing the LLM.<br/>"
        "<b>Alternatives:</b> ChromaDB, Qdrant, BM25 keyword search (lacks semantic synonym matching).<br/>"
        "<b>Key Concepts:</b> Dense vector embeddings, cosine similarity via <code>IndexFlatIP</code>, normalized vector dot product."
    ))

    story.append(sub_sub_header("4. SQLite with Write-Ahead Logging (WAL)"))
    story.append(p(
        "<b>What it is:</b> An in-process, zero-configuration relational database engine configured in WAL mode.<br/>"
        "<b>Where used:</b> <code>meta.db</code> (sessions, conversations, history) and demo databases (<code>demo_hospital.db</code>, <code>demo_ecommerce.db</code>).<br/>"
        "<b>Why used:</b> Eliminates separate database server overhead. Standard SQLite locks the entire database file during writes; enabling "
        "<code>PRAGMA journal_mode=WAL</code> and <code>PRAGMA synchronous=NORMAL</code> permits concurrent readers while a write proceeds.<br/>"
        "<b>What happens if removed:</b> Metadata persistence fails, multi-turn conversation history is lost across restarts, and demo datasets cannot be queried.<br/>"
        "<b>Alternatives:</b> PostgreSQL, MySQL, DuckDB.<br/>"
        "<b>Key Concepts:</b> Write-Ahead Logging, ACID transactions, check_same_thread=False, PRAGMA tuning."
    ))

    # =========================================================================
    # SECTION 3: COMPLETE PROJECT FOLDER STRUCTURE
    # =========================================================================
    story.extend(sec_header(3, "Complete Project Folder Structure"))
    story.append(p(
        "The project is structured as a decoupled monorepo containing a modern React frontend, a FastAPI Python backend, "
        "persisted relational datasets, automated test suites, deployment scripts, and architecture documentation."
    ))

    tree_str = """
NL2SQL-Full-project-main/
|-- Dockerfile                     # Multi-stage Dockerfile: Node 20 build + Python 3.11 slim runtime
|-- API.md                         # Complete REST API specification and endpoint documentation
|-- ARCHITECTURE.md                # System architecture, layer contracts, and security rules
|-- IMPLEMENTATION_REPORT.md       # Implementation milestone verification report
|-- LIMITATIONS.md                 # Operational boundaries, design trade-offs, and roadmap
|-- README.md                      # High-level overview, quickstart instructions, and test guide
|-- TEST_REPORT.md                 # Test suite verification breakdown (166 automated tests)
|
+-- frontend/                      # React 18 + Vite Single Page Application (SPA)
|   |-- package.json               # Frontend dependencies (React, Vite, Chart.js, Tailwind, Axios)
|   |-- vite.config.js             # Vite bundler configuration with proxy and asset hashing
|   |-- tailwind.config.js         # Tailwind utility styling theme and color palette definitions
|   |-- index.html                 # Single page HTML entry point with viewport and metadata
|   +-- src/
|       |-- App.jsx                # Root application coordinator managing session, theme, and screens
|       |-- App.css / index.css    # Custom styling rules and Tailwind utility directives
|       |-- main.jsx               # React DOM mounting entry point
|       +-- api/
|       |   +-- client.js          # Axios REST client with error normalization and endpoint wrappers
|       +-- components/
|       |   |-- ConnectDBScreen.jsx# Initial landing screen: demo selector, CSV/SQL upload, URI input
|       |   |-- ChatWindow.jsx     # Main chat workspace: message stream, query input, voice button
|       |   |-- MessageBubble.jsx  # Interactive message card: SQL drawer, chart viewer, feedback
|       |   |-- ChartPanel.jsx     # Dynamic Chart.js renderer (Bar, Line, KPI, Data Table)
|       |   |-- ConfirmModal.jsx   # Modal dialog for two-phase write confirmation (INSERT/UPDATE/DELETE)
|       |   |-- LearnSQLModal.jsx  # Interactive pedagogical popup explaining generated SQL
|       |   |-- SQLDrawer.jsx      # Slide-out syntax-highlighted SQL drawer
|       |   |-- SQLPreviewPanel.jsx# Live SQL preview pane with execution controls
|       |   |-- VoiceButton.jsx    # Web Speech API speech-to-text button with recording state
|       |   |-- HistorySidebar.jsx # Sidebar listing historical conversation threads with search
|       |   +-- HelpSidebar.jsx    # Contextual help pane showing schema hints and sample queries
|       +-- utils/
|           |-- learnSqlGenerator.js# In-browser pedagogical SQL engine generating 8-stage lessons
|           |-- messageFormatter.js# Sanitizer and markdown formatter for chat text
|           +-- media.js           # Audio playback helpers for voice interaction
|
+-- nl2sql-backend/                # Python 3.11 FastAPI Application Engine
|   |-- requirements.txt           # Python package requirements (FastAPI, PyTorch, FAISS, sqlglot)
|   |-- pytest.ini                 # Pytest configuration (test discovery, warning filters)
|   |-- run_tests.py               # Standalone test runner script
|   +-- app/
|       |-- main.py                # FastAPI app initialization, CORS, security middleware, SPA mount
|       |-- config.py              # Environment variables, directory paths, Gemini API key hygiene
|       +-- database/              # Universal Database Abstraction Layer
|       |   |-- base.py            # BaseDatabaseAdapter abstract class defining universal contracts
|       |   |-- manager.py         # DatabaseConnectionManager factory and adapter registry
|       |   |-- sqlite_adapter.py  # SQLiteAdapter implementation (demo DBs, uploaded files, WAL)
|       |   +-- postgres_adapter.py# PostgreSQLAdapter implementation (SQLAlchemy, information_schema)
|       +-- models/
|       |   +-- meta_db.py         # SQLAlchemy models for meta.db: sessions, conversations, query_history
|       +-- routers/
|       |   |-- connect_db.py      # Endpoints: /api/connect-db, /api/upload-data, /api/session-status
|       |   |-- query.py           # Endpoints: /api/query, /api/confirm-write, rate limiting
|       |   +-- conversations.py   # Endpoints: /api/conversations, /messages, title generation
|       +-- services/
|           |-- sql_generator.py   # Core AI engine: Gemini synthesis, multilingual, phonetic, ambiguity
|           |-- sql_validator.py   # Security safety gate: sqlglot AST parsing, injection/DDL block
|           |-- execution_engine.py# Safe SELECT execution, transactional writes, duplicate check
|           |-- rag_service.py     # Schema-aware RAG: SentenceTransformer embeddings + FAISS index
|           +-- session_store.py   # In-memory session registry with fallback restoration from meta.db
|   +-- data/                      # Persisted SQLite databases
|   |   |-- meta.db                # System metadata store (sessions, conversations, query history)
|   |   |-- demo_hospital.db       # Hospital demo database (patients, doctors, appointments, bills)
|   |   +-- demo_ecommerce.db      # E-commerce demo database (customers, products, orders, items)
|   +-- tests/                     # Automated Test Suite (17 test modules, 166 test cases)
|       |-- conftest.py            # Pytest fixtures: test database setup, sample sessions, TestClient
|       |-- test_adapters_and_writes.py # Tests for adapter interface, schema extraction, writes
|       |-- test_sql_validator.py  # 44 tests for AST validation, comments, DDL rejection, WHERE clauses
|       |-- test_security.py       # 23 tests for rate limiting, security headers, file upload guards
|       |-- test_rag.py            # 11 tests for FAISS index lifecycle and table retrieval
|       |-- test_multilingual.py   # 9 tests for Tamil script, Thanglish, and translation integrity
|       |-- test_self_correction.py# 8 tests for autonomous retry loop and error feedback
|       +-- ...                    # Additional unit and integration test suites
"""
    story.extend(ascii_diagram(tree_str, "Complete Project Directory Hierarchy"))

    # =========================================================================
    # SECTION 4: COMPLETE FILE/MODULE INVENTORY
    # =========================================================================
    story.extend(sec_header(4, "Complete File & Module Inventory"))
    story.append(p(
        "The following master inventory specifies the exact architectural layer, responsibility, critical functions, "
        "and dependencies for every production source file in the repository."
    ))

    inv_table = [
        ["File", "Module / Layer", "Purpose", "Important Classes / Functions", "Dependencies"],
        ["app/main.py", "API Gateway", "ASGI application initialization, security middleware, SPA routing", "SecurityHeadersMiddleware, lifespan(), serve_spa_frontend()", "FastAPI, Starlette, config, routers"],
        ["app/config.py", "Configuration", "Path resolution, environment configuration, Gemini API key hygiene", "BASE_DIR, DATA_DIR, IS_PRODUCTION, GEMINI_API_KEY", "dotenv, os, pathlib"],
        ["app/database/base.py", "DB Abstraction", "Abstract base class defining universal database adapter interface", "BaseDatabaseAdapter, extract_full_schema(), execute_query()", "abc, typing"],
        ["app/database/manager.py", "DB Abstraction", "Factory and registry managing active adapters keyed by session_id", "DatabaseConnectionManager, create_adapter(), get_adapter()", "base, sqlite_adapter, postgres_adapter"],
        ["app/database/sqlite_adapter.py", "DB Abstraction", "Concrete SQLite adapter with deep schema extraction and WAL tuning", "SQLiteAdapter, extract_full_schema(), execute_write()", "sqlite3, base, execution_engine"],
        ["app/database/postgres_adapter.py", "DB Abstraction", "Concrete PostgreSQL adapter inspecting information_schema", "PostgreSQLAdapter, validate_connection(), _check_driver()", "SQLAlchemy, psycopg2/asyncpg"],
        ["app/models/meta_db.py", "Persistence", "SQLAlchemy models and database initialization for system metadata", "SessionModel, ConversationModel, QueryHistoryModel, init_db()", "SQLAlchemy, sqlite3, config"],
        ["app/routers/connect_db.py", "REST API", "Database connection, CSV/SQL upload parsing, and schema inspection", "connect_db(), upload_data(), inspect_db_schema_and_samples()", "FastAPI, SQLAlchemy, manager, config"],
        ["app/routers/query.py", "REST API", "Query translation, two-tier rate limiting, staged writes, retry loop", "handle_query(), confirm_write(), check_rate_limit()", "sql_generator, sql_validator, engine"],
        ["app/routers/conversations.py", "REST API", "Conversation thread management, history retrieval, auto-titling", "create_conversation(), list_conversations(), get_messages()", "meta_db, FastAPI, pydantic"],
        ["app/services/sql_generator.py", "Core AI Engine", "Gemini synthesis, multilingual detection, phonetic correction, cache", "generate_sql(), regenerate_sql(), detect_input_language()", "google.generativeai, rag_service"],
        ["app/services/sql_validator.py", "Security / Safety", "sqlglot AST validation, comment stripping, DDL rejection", "validate_sql(), validate_write_sql(), _strip_strings()", "sqlglot, exp, re"],
        ["app/services/execution_engine.py", "Execution", "Safe SELECT execution, transactional writes, duplicate insert check", "run_select(), run_write(), check_duplicate_insert()", "sqlite3, sqlglot, manager"],
        ["app/services/rag_service.py", "AI / Retrieval", "SentenceTransformers + FAISS schema-aware table retrieval", "build_schema_index(), retrieve_relevant_tables()", "sentence_transformers, faiss, numpy"],
        ["app/services/session_store.py", "State Store", "In-memory session registry with fallback restoration from meta.db", "get_session(), set_session(), SESSION_STORE", "meta_db, rag_service"],
        ["frontend/src/App.jsx", "Frontend Root", "Top-level application orchestrator, theme manager, session gate", "App(), handleConnect(), handleDisconnect(), refreshConversations()", "React, ConnectDBScreen, ChatWindow"],
        ["frontend/src/api/client.js", "Frontend API", "Axios client with base URL handling and unified error parsing", "connectDB(), sendQuery(), confirmWrite(), getSessionStatus()", "axios"],
        ["frontend/src/components/ChatWindow.jsx", "Frontend UI", "Main chat interface: message stream, query dispatch, follow-up state", "ChatWindow(), handleSend(), handleVoiceTranscript()", "MessageBubble, VoiceButton, client"],
        ["frontend/src/components/MessageBubble.jsx", "Frontend UI", "Message rendering: SQL drawer, ChartPanel, LearnSQLModal trigger", "MessageBubble(), renderChart(), renderSqlPreview()", "ChartPanel, LearnSQLModal, Lucide"],
        ["frontend/src/components/ConfirmModal.jsx", "Frontend UI", "Modal dialog for staged two-phase write confirmation", "ConfirmModal(), handleConfirm(), handleCancel()", "React, Lucide React"],
        ["frontend/src/components/ChartPanel.jsx", "Frontend UI", "Automatic Chart.js visualization renderer", "ChartPanel(), prepareBarData(), prepareLineData(), KPI Card", "chart.js, react-chartjs-2"],
        ["frontend/src/components/LearnSQLModal.jsx", "Frontend UI", "Interactive educational dialog teaching generated SQL concepts", "LearnSQLModal(), renderTabs(), renderLessonBreakdown()", "learnSqlGenerator, Lucide"],
        ["frontend/src/components/VoiceButton.jsx", "Frontend UI", "Web Speech API microphone controller with recording visualizer", "VoiceButton(), startListening(), stopListening()", "Web Speech API, Lucide"],
        ["frontend/src/utils/learnSqlGenerator.js", "Frontend Logic", "Pedagogical engine generating 8-stage SQL explanations in 3 languages", "generateSqlLessons(), parseSqlDetails(), detectLanguage()", "JavaScript RegExp, Unicode"],
    ]
    story.append(make_table(inv_table, [85, 65, 120, 150, 100]))
    story.append(Spacer(1, 10))

    return story

