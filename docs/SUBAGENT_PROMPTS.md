# Sub-Agent Prompts (5 Parallel Tracks)

Use these prompts as-is to dispatch parallel sub-agents. Each sub-agent should only edit its owned files unless explicitly listed as shared.

## Prompt 1: Platform + Data Contracts Agent
You are Sub-Agent 1 for the Tax Assistant MVP. Implement the backend platform foundation and canonical data contracts.

### Objective
Create the app bootstrapping, settings, persistence, and shared domain model needed by all other agents.

### Owned Scope
- `tax_assistant/main.py`
- `tax_assistant/config.py`
- `tax_assistant/db.py`
- `tax_assistant/models.py`
- `tax_assistant/schemas.py` (shared; coordinate with API contract in this prompt)

### Requirements
- FastAPI app with startup DB initialization.
- SQLite-backed SQLModel persistence.
- Core entities:
  - `TaxReturn`, `Document`, `ExtractionJob`, `TaxFact`, `EvidenceLink`, `Issue`, `OptimizationScenario`, `Attestation`, `ApprovalEvent`.
- Add `POST /v1/returns` and `GET /healthz`.
- Ensure schema supports:
  - tax year, filing status, primary state
  - role-based approvals
  - issue severity/blocking status
  - evidence-link provenance

### Acceptance Criteria
- App starts with `uvicorn tax_assistant.main:app --reload`.
- `POST /v1/returns` creates a row and returns stable ID.
- DB schema includes all listed entities.
- No TODO placeholders in owned files.

### Constraints
- Do not implement extraction/rules/optimization logic.
- Keep contracts backward-compatible for downstream agents.

---

## Prompt 2: Ingestion + Extraction Agent
You are Sub-Agent 2 for the Tax Assistant MVP. Implement document ingestion, classification, and extraction.

### Objective
Build upload and extraction workflows for PDF/CSV/screenshots/photos and persist extracted tax facts + evidence links.

### Owned Scope
- `tax_assistant/services/document_service.py`
- `tax_assistant/services/extraction_service.py`
- `tax_assistant/api/routes.py` (upload/extract routes only)

### Requirements
- `POST /v1/documents/upload` with metadata: `return_id`, `tax_year`, `owner`, `source_type`, `file`.
- SHA-256 dedupe by `return_id` + file hash.
- Rule-based document classification (`w2`, `1099-*`, `8606`, `5498`, `crypto`, etc.).
- `POST /v1/documents/{id}/extract`:
  - PDF text extraction first.
  - OCR fallback for images/screenshots/photos.
  - CSV parsing for tax facts.
- Persist `TaxFact` and `EvidenceLink` with confidence + locator.

### Acceptance Criteria
- Duplicate upload returns existing `document_id` and `duplicate=true`.
- Extraction job is persisted with status transitions.
- At least one canonical extraction path works end-to-end for CSV.
- Extracted facts are queryable via `GET /v1/returns/{return_id}/facts`.

### Constraints
- Do not create optimization/export logic.
- If OCR unavailable, degrade gracefully and mark low confidence.

---

## Prompt 3: Rules + Confidence Gate Agent
You are Sub-Agent 3 for the Tax Assistant MVP. Implement validation rules, issue generation, and filing readiness gates.

### Objective
Enforce evidence-first correctness and create blockers before export.

### Owned Scope
- `tax_assistant/services/rules_engine.py`
- `tax_assistant/services/confidence_service.py`
- `tax_assistant/api/routes.py` (issues/readiness integration only)

### Requirements
- Implement `GET /v1/returns/{return_id}/issues`.
- Run checks for:
  - conflicting values for same material form line
  - missing prior-year 8606 when Roth conversion evidence exists
  - screenshot/photo-only evidence for material fields
  - missing evidence coverage on material facts
- Compute readiness summary:
  - `ready_to_file`
  - material fields total
  - evidenced or attested count
  - evidence coverage percentage
  - open blocking issue count and blocker messages

### Acceptance Criteria
- Blocking issues appear for missing 8606 in backdoor Roth scenario.
- Conflicting 1099 values generate high-severity blocking issue.
- Readiness false when blocking issues exist.
- Rules are idempotent (re-running does not duplicate same open system issue).

### Constraints
- No UI work.
- Do not change upload/extraction behavior.

---

## Prompt 4: Optimization + Collaboration Agent
You are Sub-Agent 4 for the Tax Assistant MVP. Implement scenario optimization plus attest/approval collaboration workflows.

### Objective
Generate legal tax scenarios and support role-based human review events.

### Owned Scope
- `tax_assistant/services/optimization_service.py`
- `tax_assistant/api/routes.py` (optimize/attest/approve routes only)

### Requirements
- `POST /v1/returns/{return_id}/optimize` returns ranked scenarios with:
  - assumptions
  - `tax_outcome`
  - `savings_delta`
  - `risk_score`
  - required evidence list
- `POST /v1/returns/{return_id}/attest`:
  - attach rationale to `fact_id`
  - mark fact as attested
- `POST /v1/returns/{return_id}/approve`:
  - store approval events by role (`taxpayer`, `spouse`, `cpa`)
  - return approval summary by role

### Acceptance Criteria
- At least 2 scenarios returned when enough facts exist.
- Attesting a fact updates readiness numerator in confidence checks.
- Approval event history is persisted and role-attributed.

### Constraints
- Keep risk scoring explainable and deterministic.
- Do not make export decisions in this layer.

---

## Prompt 5: Export + Web App + Test Agent
You are Sub-Agent 5 for the Tax Assistant MVP. Implement FreeTaxUSA export generation, a lightweight collaborative web UI, and end-to-end tests.

### Objective
Ship user-facing workflow from upload through export with robust test coverage.

### Owned Scope
- `tax_assistant/services/export_service.py`
- `tax_assistant/static/*`
- `tests/*`
- `README.md`
- `tax_assistant/api/routes.py` (export route + optional UI route)

### Requirements
- `GET /v1/returns/{return_id}/export/freetaxusa`:
  - fail if readiness gate not met
  - return field mapping packet + unresolved question queue + evidence report + audit summary
- Lightweight web inbox UI:
  - create return
  - upload docs
  - run extraction
  - view facts/issues
  - run optimize
  - attest/approve
  - run export
- Add pytest coverage for:
  - golden flow (W-2/CSV-style facts)
  - conflicting values issue
  - missing 8606 blocker
  - screenshot-only evidence blocker
  - export blocked until gate passes

### Acceptance Criteria
- E2E test proves export gate blocks and then passes after blockers resolved/attested.
- UI can execute full happy-path via browser without manual API calls.
- README includes setup, run, and test commands.

### Constraints
- Keep UI intentionally minimal but fully functional.
- Do not introduce external paid services.
