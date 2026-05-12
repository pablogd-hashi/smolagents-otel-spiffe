# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY agents/executor/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY agents/shared /app/agents/shared
COPY agents/executor /app/agents/executor

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fs http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "agents.executor.main:app", "--host", "0.0.0.0", "--port", "8000"]
