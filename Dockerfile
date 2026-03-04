FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY tax_assistant ./tax_assistant

RUN pip install --upgrade pip && \
    pip install .

RUN mkdir -p /app/data/uploads

ENV TAX_ASSISTANT_DATABASE_URL=sqlite:///./data/tax_assistant.db \
    TAX_ASSISTANT_STORAGE_DIR=./data/uploads \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8000')}/healthz\")"

CMD ["sh", "-c", "uvicorn tax_assistant.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
