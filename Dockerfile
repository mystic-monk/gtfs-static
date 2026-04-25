FROM python:3.11-slim

WORKDIR /app

# System dependencies for pyarrow and chardet
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source (better layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[core,api,remediation]"

# Copy application source
COPY src/ ./src/

# Persistent output directory (mount as volume in production)
RUN mkdir -p /app/outputs/bronze \
              /app/outputs/silver \
              /app/outputs/gold \
              /app/outputs/quarantine \
              /app/outputs/profiles \
              /app/outputs/monitoring \
              /app/outputs/remediation \
              /app/logs

# Non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.api.main"]
