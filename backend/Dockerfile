# Sovereign On-Premise Agentic AI Workbench - FastAPI Backend Dockerfile
# Base: Official Python 3.11 Slim Linux Image
FROM python:3.11-slim

# Prevent bytecode generation and configure unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATA_DIR=/app/data \
    ANONYMIZED_TELEMETRY=false \
    CHROMA_TELEMETRY=false

WORKDIR /app

# Install curl for container healthcheck and create unprivileged non-root user
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10001 sovereign && \
    useradd -u 10001 -g sovereign -d /app -s /sbin/nologin -c "Sovereign Backend App User" appuser

# Install pinned runtime dependencies only (eval/matplotlib excluded)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY backend/ /app/backend/

# Create persistent data directory and assign ownership to non-root user
RUN mkdir -p /app/data/uploads /app/data/chroma && \
    chown -R appuser:sovereign /app

# Switch to non-root user
USER appuser

# Expose backend port (bound to localhost on host by compose)
EXPOSE 8000

# Container healthcheck against lightweight /live liveness endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/live || exit 1

# Start FastAPI application
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
