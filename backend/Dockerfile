# ClauseIQ Backend Dockerfile
# Python 3.13 + FastAPI

FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared types package first (used by backend requirements)
COPY shared /app/shared

# Switch to backend directory
WORKDIR /app/backend

# Copy requirements first for better layer caching
COPY backend/requirements.txt .

# Modify requirements.txt to use correct shared path and install dependencies
# (this includes shared package install via -e /app/shared)
RUN sed -i 's|-e ../shared|-e /app/shared|g' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend/ .

# Create directories for logs and storage
RUN mkdir -p logs documents_storage

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
