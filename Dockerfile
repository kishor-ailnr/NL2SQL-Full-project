# ===========================================================================
# Stage 1: Build Frontend Assets
# ===========================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
# Build production bundle with relative API paths (same-origin unified deploy)
ENV VITE_API_BASE_URL=""
RUN npm run build

# ===========================================================================
# Stage 2: Python Backend Runtime & Unified SPA Serving
# ===========================================================================
FROM python:3.11-slim AS runtime

# Set runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PORT=8000

WORKDIR /app

# Install system dependencies (sqlite3 and curl for health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY nl2sql-backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code and demo databases
COPY nl2sql-backend/ ./nl2sql-backend/

# Copy built frontend assets from Stage 1 into the expected location
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Set working directory to the backend folder so relative imports & data paths align
WORKDIR /app/nl2sql-backend

# Expose default port (Render will bind to $PORT dynamically)
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start Uvicorn server using shell form to expand $PORT for Render / Cloud Run
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
