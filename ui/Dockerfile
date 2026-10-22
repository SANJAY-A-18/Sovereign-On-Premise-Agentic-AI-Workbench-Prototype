# Sovereign On-Premise Agentic AI Workbench - Streamlit UI Dockerfile
# Base: Official Python 3.11 Slim Linux Image
FROM python:3.11-slim

# Prevent bytecode generation and configure unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Install curl for container healthcheck and create unprivileged non-root user
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 10001 sovereign && \
    useradd -u 10001 -g sovereign -d /app -s /sbin/nologin -c "Sovereign UI App User" appuser

# Install pinned runtime dependencies only (eval/matplotlib excluded)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy Streamlit application code
COPY ui/ /app/ui/

# Assign ownership to non-root user
RUN chown -R appuser:sovereign /app

# Switch to non-root user
USER appuser

# Expose UI port (bound to localhost on host by compose)
EXPOSE 8501

# Container healthcheck against Streamlit internal health endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8501/_stcore/health || exit 1

# Start Streamlit application
CMD ["streamlit", "run", "ui/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
