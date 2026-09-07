# =============================================================================
#  Backend image — shared by the api, worker and cli services.
#  Multi-stage so the runtime layer carries no build toolchain.
# =============================================================================
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --timeout 90 --retries 6 -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

# libpq for psycopg, curl for the container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY config/ ./config/
COPY db/ ./db/
COPY src/ ./src/
COPY tests/ ./tests/

RUN mkdir -p /app/artifacts && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

# Default is the API; compose overrides `command` for worker and cli.
CMD ["uvicorn", "priority_engine.api:app", "--host", "0.0.0.0", "--port", "8000"]
