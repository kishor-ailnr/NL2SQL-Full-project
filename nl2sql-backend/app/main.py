import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, FileResponse
from starlette.staticfiles import StaticFiles
from app.config import IS_PRODUCTION, WORKSPACE_DIR, FRONTEND_DIST
from app.models.meta_db import init_db
from app.routers import connect_db, query, conversations

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security response headers to every request.

    Headers added:
    - X-Content-Type-Options: nosniff          — prevents MIME-type sniffing
    - X-Frame-Options: DENY                    — blocks framing (clickjacking)
    - Content-Security-Policy                  — restricts resource origins for SPA
    - Referrer-Policy                          — limits referrer leakage
    - X-XSS-Protection                         — legacy XSS filter hint (belt+suspenders)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # CSP for a single-page application served from its own origin.
        # - default-src 'self'                   → default same-origin
        # - script-src 'self' 'unsafe-inline'    → allow SPA bootstrap and inline scripts
        # - style-src 'self' 'unsafe-inline' https://fonts.googleapis.com → allow component styles and Google Fonts CSS
        # - img-src 'self' data: blob: https:    → allow chart blobs, avatars, data URIs
        # - font-src 'self' data: https://fonts.gstatic.com → allow local and Google Fonts webfonts
        # - connect-src 'self' https:            → allow backend API calls and external services
        # - frame-ancestors 'none'               → equivalent of X-Frame-Options: DENY for CSP3
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none';"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize metadata database tables on startup
    init_db()
    # Pre-warm demo schema cache for instant connection
    connect_db.preload_demo_cache()
    env_label = "production" if IS_PRODUCTION else "development"
    logger.info("NL2SQL backend starting in %s mode.", env_label)
    yield


app = FastAPI(
    title="NL2SQL Assistant Backend",
    description="Natural Language to SQL Assistant Backend API",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — environment-aware
# ---------------------------------------------------------------------------
# Production: frontend is served from FastAPI itself (same origin), so only
# the Vercel deployment URL is allowed as a cross-origin caller.
# Development: also allow the Vite dev server (localhost:5173 / :3000).
# ---------------------------------------------------------------------------
if IS_PRODUCTION:
    cors_origins = [
        "https://project-final-nl-2-sql.vercel.app",
        "https://project-final-nl-2-sql.vercel.app/",
    ]
    cors_origin_regex = r"https://.*\.vercel\.app/?"
    cors_allow_credentials = False  # no cookies needed; keeps surface area minimal
else:
    # Development: allow local Vite/React dev servers
    cors_origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://project-final-nl-2-sql.vercel.app",
    ]
    cors_origin_regex = r"https://.*\.vercel\.app/?"
    cors_allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=cors_allow_credentials,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Security headers applied to every response (after CORS so CORS headers win)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global fallback exception handler: logs stack trace server-side without leaking internals to clients."""
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred. Please try again later."},
    )


# Register Routers
app.include_router(connect_db.router, prefix="/api", tags=["Database Connection"])
app.include_router(query.router, prefix="/api", tags=["Query"])
app.include_router(conversations.router, prefix="/api", tags=["Conversations"])


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Static Assets & SPA Serving with Cache-Control Headers
# ---------------------------------------------------------------------------
class CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that attaches long-lived Cache-Control headers to hashed assets."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        # Content-hashed assets (Vite generates e.g. index-DSoOfJn_.js) are safe to cache for 1 year
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response



if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", CachedStaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa_frontend(full_path: str):
        # Do not intercept API, health, or documentation routes
        if (
            full_path.startswith("api/")
            or full_path == "api"
            or full_path == "health"
            or full_path.startswith("docs")
            or full_path.startswith("openapi.json")
        ):
            raise HTTPException(status_code=404, detail="Not found")

        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            resp = FileResponse(str(file_path))
            if "/assets/" in str(file_path).replace("\\", "/"):
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                resp.headers["Cache-Control"] = "no-cache"
            return resp

        # Fallback to index.html for Single Page Application client-side routing
        index_file = FRONTEND_DIST / "index.html"
        if index_file.is_file():
            resp = FileResponse(str(index_file))
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        raise HTTPException(status_code=404, detail="Frontend build files not found")


