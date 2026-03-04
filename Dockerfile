FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY tax_assistant ./tax_assistant

RUN uv sync --frozen --no-dev

RUN mkdir -p /app/data/uploads

ENV PATH="/app/.venv/bin:$PATH" \
    TAX_ASSISTANT_DATABASE_URL=sqlite:///./data/tax_assistant.db \
    TAX_ASSISTANT_STORAGE_DIR=./data/uploads \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8000')}/healthz\")"

CMD ["sh", "-c", "uv run --no-sync uvicorn tax_assistant.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
