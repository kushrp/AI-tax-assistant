# Tax Assistant MVP

Collaborative tax workflow MVP for TY2025 (US Federal + NY) with:
- document upload + extraction
- fact and issue review
- optimization scenarios
- attestation/approval trail
- FreeTaxUSA export packet gated by readiness

## Requirements
- Python 3.11+

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## Run the App
```bash
uvicorn tax_assistant.main:app --reload
```

Open:
- UI: http://127.0.0.1:8000/app
- API docs: http://127.0.0.1:8000/docs

## Run Tests
```bash
pytest
```

## Minimal Happy Path (UI)
1. Create a return.
2. Upload one or more CSV/PDF docs.
3. Extract all docs.
4. Load facts/issues/readiness.
5. Run optimize.
6. Optionally attest facts and approve.
7. Run export (`GET /v1/returns/{return_id}/export/freetaxusa` behind the UI button).

Export is blocked until readiness is true (no blocking issues, full material fact coverage/evidence/attestation, and no unmapped material facts).
