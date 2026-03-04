# Collaborative LLM Tax Agent Implementation Plan

## Scope and Objective
Build an MVP web-based collaborative tax copilot for **US Federal + New York (Tax Year 2025)** that:
- Ingests PDFs, CSVs, screenshots, and photos
- Extracts tax facts and links each material value to source evidence
- Optimizes legal tax outcome under an evidence-first risk posture
- Produces a **FreeTaxUSA-ready export package**
- Blocks export until material fields are evidenced or explicitly attested
- Is deployable as a free-tier web app path on **Railway and/or Vercel**

## Working Model
- Product mode: Collaborative copilot (human-in-the-loop)
- Users: Taxpayer, spouse, optional CPA reviewer
- Filing path: FreeTaxUSA-first manual final entry
- Privacy: Hybrid secure, strict PII controls, 90-day working retention
- Hosting mode: Cloud-hosted MVP with free-tier constraints (stateless runtime, env-configured services)

## FreeTaxUSA Format Understanding and Mapping Strategy
Treat FreeTaxUSA as a **versioned mapping target** while keeping our internal tax facts canonical.

### Canonical-First Principle
- Keep internal fact IDs stable (`1040.line1a.wages`, `schedule_d.total_proceeds`, etc.).
- Do not couple extraction/rules logic to FreeTaxUSA UI labels.
- Only export layer translates canonical facts to FreeTaxUSA field keys.

### FreeTaxUSA Field Dictionary (Tax Year 2025)
- Build and maintain `docs/FREETAXUSA_MAPPING_SPEC.md` as source of truth.
- Each mapping entry must include:
  - FreeTaxUSA section/screen path
  - Internal export field key
  - Data type/format constraints
  - Required/optional behavior
  - Conditional visibility logic (when field appears)
  - Evidence requirements for field population

### Controlled Discovery Process
- Use synthetic and anonymized test returns to traverse all relevant FreeTaxUSA screens:
  - W-2 only
  - W-2 + 1099-INT/1099-DIV
  - 1099-B capital gains/losses
  - Backdoor Roth conversion with prior-year 8606
  - Crypto transaction summaries
  - Federal + New York state flow
- Record mapping behavior and edge constraints into the mapping spec.
- No autonomous filing automation in MVP; manual validation path only.

### Reconciliation and Validation
- Add deterministic mapping tests that compare:
  - canonical facts produced by engine
  - expected FreeTaxUSA field packet
  - final tax outcome deltas (refund/owed estimates) for benchmark scenarios
- Any mismatch must open a blocking issue in integration QA.

### Drift Control and Versioning
- Version mapping packs by filing year (e.g., `freetaxusa_2025`).
- Re-run mapping validation suite at start of every filing season.
- If UI/field drift is detected:
  - mark impacted fields as `unverified`
  - route to unresolved question queue
  - block final export for impacted material fields until remapped

### Ownership
- **Primary owner:** Agent F (Export + UI + E2E).
- **Supporting owners:** Agent D (readiness/blocking policy), Agent A (schema/version metadata).

## Free-Tier Hosting Strategy (Vercel/Railway)
Make deployment constraints first-class so local-only assumptions do not block production hosting.

### Hosting Constraints
- Runtime must be stateless; do not depend on local persistent disk.
- All secrets/config must come from environment variables.
- Document storage must support hosted object storage (keep local storage only for dev/test).
- API and UI must tolerate cold starts and low-resource free-tier environments.

### Deployment Targets
1. **Railway-first MVP (recommended first production path)**
   - Deploy FastAPI + web UI as one service from containerized app runtime.
   - Use managed/external Postgres via `DATABASE_URL`.
   - Use S3-compatible blob storage via configured provider.
2. **Vercel-compatible path**
   - Host web UI on Vercel.
   - Keep API behind a public base URL with same REST contracts (`/v1/...`) so UI can switch by `API_BASE_URL`.
   - Preserve same auth, readiness gating, and export behavior across hosts.

### Deployment Deliverables (Cross-Agent)
- `Dockerfile` + production start command and health check wiring.
- `docs/DEPLOYMENT.md` with Railway and Vercel setup steps.
- Environment template (`.env.example`) for DB, storage, CORS, and app secrets.
- Hosted smoke test covering upload, extract, issues, optimize, and export-readiness gate.

## Parallel Sub-Agent Work Split

### Agent A: Platform + Data Foundation
**Goal:** Stand up backend skeleton, persistence, core domain model, and app bootstrapping.
- Create FastAPI app + settings + DB lifecycle
- Implement canonical data model:
  - `TaxReturn`, `Document`, `ExtractionJob`, `TaxFact`, `EvidenceLink`, `Issue`, `OptimizationScenario`, `Attestation`, `ApprovalEvent`
- Add migrations/bootstrap (`create_all` for MVP)
- Add health/readiness endpoints
- Add common error handling and response envelopes
- Make infra config fully environment-driven for hosted deployment (`DATABASE_URL`, CORS origins, storage provider)

**Deliverables:**
- `tax_assistant/main.py`
- `tax_assistant/config.py`
- `tax_assistant/db.py`
- `tax_assistant/models.py`
- `Dockerfile`
- baseline `README.md`

### Agent B: Ingestion + Classification + Storage
**Goal:** Build document upload pipeline and classification metadata.
- Implement `POST /v1/documents/upload`
- Compute SHA-256 deduplication hash
- Persist document metadata (tax year, owner, source type)
- Pluggable blob storage abstraction (local dev + hosted object storage)
- Rule-based doc classifier (W-2, 1099 family, 8606, 5498, etc.)

**Deliverables:**
- `tax_assistant/services/document_service.py`
- Upload route wiring in `tax_assistant/api/routes.py`
- Unit tests for dedupe + classifier

### Agent C: Extraction + Normalization + Evidence Graph
**Goal:** Extract structured facts from docs with confidence and provenance.
- Implement `POST /v1/documents/{id}/extract`
- PDF text extraction first; OCR fallback for scanned/image docs
- CSV parser for broker/crypto transaction files
- Canonical `TaxFact` generation with `form_line_ref`, `value`, `materiality`, `confidence`
- Create `EvidenceLink` records for each fact

**Deliverables:**
- `tax_assistant/services/extraction_service.py`
- extraction API route integration
- extraction scenario tests (PDF/CSV/screenshot/photo)

### Agent D: Tax Rules + Confidence Gate + Issues
**Goal:** Enforce correctness, consistency, and readiness requirements.
- Implement checks:
  - Conflicting values across docs/forms
  - Missing prior-year 8606 for backdoor Roth continuity
  - Screenshot/photo-only evidence for material values
  - Missing evidence coverage on material fields
- Implement issue creation + lifecycle (`open/resolved`)
- Implement confidence gate used by export
- Implement `GET /v1/returns/{return_id}/issues`

**Deliverables:**
- `tax_assistant/services/rules_engine.py`
- `tax_assistant/services/confidence_service.py`
- issue endpoints + regression tests

### Agent E: Optimization + Collaboration + Approvals
**Goal:** Rank legal filing scenarios and support multi-party review.
- Implement `POST /v1/returns/{return_id}/optimize`
- Implement `POST /v1/returns/{return_id}/attest`
- Implement `POST /v1/returns/{return_id}/approve`
- Role-based approvals (`taxpayer`, `spouse`, optional `cpa`)
- Scenario output: savings delta, risk score, required evidence

**Deliverables:**
- `tax_assistant/services/optimization_service.py`
- collaboration workflows in API routes
- approval/attestation tests

### Agent F: Export + Web Inbox UI + E2E Validation
**Goal:** Generate filing packet and provide usable collaborative interface.
- Implement `GET /v1/returns/{return_id}/export/freetaxusa`
- Map known facts to FreeTaxUSA field keys
- Emit unresolved question queue + evidence report + audit summary
- Build lightweight web UI (document inbox, extraction status, issues, optimize, approvals, export)
- Add end-to-end tests for golden and edge scenarios
- Add deployment configs and hosted smoke validation (Railway deploy + Vercel-compatible UI base URL)

**Deliverables:**
- `tax_assistant/services/export_service.py`
- `tax_assistant/static/` UI assets
- `tests/test_e2e_workflows.py`

## Contract-First Interfaces (Shared Across Agents)

### Core APIs
- `POST /v1/documents/upload`
- `POST /v1/documents/{id}/extract`
- `GET /v1/returns/{return_id}/facts`
- `GET /v1/returns/{return_id}/issues`
- `POST /v1/returns/{return_id}/optimize`
- `POST /v1/returns/{return_id}/attest`
- `POST /v1/returns/{return_id}/approve`
- `GET /v1/returns/{return_id}/export/freetaxusa`

### Shared Type Contracts
- `TaxFact`
- `EvidenceLink`
- `Issue`
- `OptimizationScenario`
- `ApprovalEvent`

## Parallel Execution Order and Dependencies
1. **Start in parallel:** Agents A, B, C
2. **Then parallel:** Agent D (depends on A/C), Agent E (depends on A)
3. **Then:** Agent F (depends on B/C/D/E)
4. **Final integration:** API contract verification + E2E acceptance run

## Merge and Ownership Rules
- Each agent owns only its designated files/modules.
- Shared files (`api/routes.py`, `schemas.py`) require contract lock before edits.
- Use additive migrations; avoid force rewrites of shared model fields.
- Any API contract change requires updating tests and `docs/API_CONTRACT.md` in same PR.

## Acceptance Criteria
- Material facts require evidence links or explicit attestation.
- Export blocked when blocking issues exist.
- Backdoor Roth continuity check flags missing prior-year 8606.
- Conflicting 1099 values produce blocking issues.
- FreeTaxUSA export contains mapped values + evidence references.
- Collaboration roles can approve and audit log is persisted.
- App can run in a hosted free-tier setup with external DB/storage and pass smoke workflow checks.

## Test Matrix
- Golden flows:
  - Single W-2 + standard deduction
  - MFJ with multiple W-2 + dividends
  - Backdoor Roth with prior-year basis continuity
  - Multi-broker capital gains
  - Multi-exchange crypto
- Edge/failure:
  - Conflicting 1099 values
  - OCR low-confidence extraction
  - Missing 8606
  - Screenshot-only material evidence
- Security/privacy:
  - Role access checks
  - Retention policy behavior
  - Audit trail integrity

## Supporting Documents Checklist (Input Requirements)
- Prior 2 years returns (federal + NY), all schedules/attachments
- Prior Form 8606 records
- W-2/W-2C, 1099 series, 1098, 1095, payment records
- Brokerage statements and 1099-B basis details
- IRA contribution/conversion confirmations + 1099-R + 5498
- Crypto CSV exports + wallet/explorer records + transfer evidence
- Deduction/credit receipts and related forms
- Bank statements for reconciliation support

## Implementation Notes
- This MVP does not auto-file and does not replace licensed tax/legal advice.
- Any high-risk or unsupported scenarios should be surfaced as explicit blockers with recommended CPA review.
- Re-check provider free-tier limits before go-live; keep runtime/storage choices portable between Railway and Vercel paths.
