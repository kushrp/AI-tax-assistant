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
python -m pip install -r requirements-dev.txt
```

## Run the App
```bash
python run_app.py
```

Open:
- UI: http://127.0.0.1:8000/app
- API docs: http://127.0.0.1:8000/docs

## Run Tests
```bash
python run_tests.py
```

Run live S3 integration (opt-in):
```bash
RUN_LIVE_S3_TESTS=1 \
TAX_ASSISTANT_LIVE_S3_BUCKET=your-bucket \
python run_tests.py tests/test_s3_integration_live.py
```

## Tax Rule Governance
- Use the rule-consistency merge/release checklist: [`docs/TAX_RULE_CONSISTENCY_CHECKLIST.md`](docs/TAX_RULE_CONSISTENCY_CHECKLIST.md)

## Minimal Happy Path (UI)
1. Create a return.
2. Upload one or more CSV/PDF docs.
3. Load docs and extract all docs.
4. Load facts/issues/readiness.
5. Run optimize.
6. Optionally attest facts and approve.
7. Run export (`GET /v1/returns/{return_id}/export/freetaxusa` behind the UI button).

Useful workflow APIs:
- `GET /v1/returns/{return_id}/documents`
- `POST /v1/returns/{return_id}/extract-all`
- `GET /v1/mappings/freetaxusa`
- `POST /v1/mappings/freetaxusa/overrides` (CPA role)
- `POST /v1/issues/{issue_id}/resolve` / `POST /v1/issues/{issue_id}/reopen` (CPA role)
- `POST /v1/admin/retention/run` (CPA role)

Export is blocked until readiness is true (no blocking issues, full material fact coverage/evidence/attestation, and no unmapped material facts).

Note:
- Attestation/approval and admin lifecycle endpoints require actor identity (header mode or bearer-token mode).
- Mapping rows marked `unverified` block export until re-verified.

Hosted smoke validation:
```bash
python scripts/hosted_smoke.py --base-url https://your-hosted-origin
```
