# Tax Rule Consistency Checklist

Use this checklist for any change that can affect tax correctness, readiness gating, or export behavior.

Current supported scope:
- Tax year: TY2025
- Jurisdictions: US Federal + NY
- Export target: FreeTaxUSA mapping pack `freetaxusa_2025`

## 1. Scope Lock (Required Before Coding)

- [ ] Confirm the change is in-scope for TY2025 US Federal + NY.
- [ ] If the change is out-of-scope, stop implementation and document the gap in a follow-up task.
- [ ] Confirm target mapping pack in [`tax_assistant/services/freetaxusa_mapping.py`](../tax_assistant/services/freetaxusa_mapping.py) (`MAPPING_PACK_VERSION`).
- [ ] Confirm contracts remain additive/backward-compatible in:
  - [`tax_assistant/models.py`](../tax_assistant/models.py)
  - [`tax_assistant/schemas.py`](../tax_assistant/schemas.py)
  - [`tax_assistant/api/routes.py`](../tax_assistant/api/routes.py)

## 2. Rule Source and Evidence Requirements

- [ ] Record the authoritative source used for the change (IRS form/instructions/publication or NY DTF guidance).
- [ ] Update mapping documentation in [`docs/FREETAXUSA_MAPPING_SPEC.md`](./FREETAXUSA_MAPPING_SPEC.md) if export keys or coverage changed.
- [ ] Keep material-field behavior evidence-first:
  - material facts must have `EvidenceLink`, or
  - be explicitly attested through role-based workflow.

## 3. Implementation Touchpoints

- [ ] Validation/blocking logic updates live in [`tax_assistant/services/rules_engine.py`](../tax_assistant/services/rules_engine.py).
- [ ] Readiness math updates live in [`tax_assistant/services/confidence_service.py`](../tax_assistant/services/confidence_service.py).
- [ ] Export gating and payload semantics updates live in [`tax_assistant/services/export_service.py`](../tax_assistant/services/export_service.py).
- [ ] Mapping additions/changes live in [`tax_assistant/services/freetaxusa_mapping.py`](../tax_assistant/services/freetaxusa_mapping.py).
- [ ] API behavior and status codes remain coherent in [`tax_assistant/api/routes.py`](../tax_assistant/api/routes.py).

## 4. Mandatory Test Coverage for Rule Changes

These tests should pass before merge for tax-rule-affecting changes.

- [ ] `tests/test_api_workflows.py::test_conflicting_values_create_blocking_issue_and_block_export`
- [ ] `tests/test_api_workflows.py::test_missing_prior_8606_blocks_then_clears_after_prior_upload`
- [ ] `tests/test_e2e_workflows.py::test_conflicting_values_issue_blocks_export`
- [ ] `tests/test_e2e_workflows.py::test_missing_8606_is_blocking_issue`
- [ ] `tests/test_e2e_workflows.py::test_screenshot_only_evidence_creates_blocker`
- [ ] `tests/test_e2e_workflows.py::test_export_gate_blocks_then_passes_after_resolving_blocker`
- [ ] `tests/test_service_logic.py::test_refresh_system_issues_is_idempotent_and_flags_missing_coverage`
- [ ] `tests/test_service_logic.py::test_refresh_system_issues_flags_unmapped_material_fields`

If you add a new blocking rule/category, add at least:
- one service-level deterministic test
- one API-level behavior test
- one end-to-end workflow test when export/readiness behavior changes

## 5. Release Gate (Must Pass)

- [ ] Run full suite:
  - `python run_tests.py`
- [ ] Run targeted rule-regression subset (fast gate):
  - `python run_tests.py tests/test_service_logic.py tests/test_api_workflows.py tests/test_e2e_workflows.py`
- [ ] Start app and verify startup contract:
  - `python run_app.py`
  - `GET /healthz` returns `200` with `{"status":"ok","database":"ok"}`
- [ ] Verify no open blocking issues for golden-flow fixture before export.
- [ ] Verify export still returns `400` when readiness is false.

## 6. Manual Review Checklist for PR Approval

- [ ] Rule category names remain stable and namespaced (`system.*`).
- [ ] No bypass path exists that skips `refresh_system_issues()` before readiness/export decisions.
- [ ] No material fact is silently dropped from readiness or export logic.
- [ ] Mapping defaults stay `verified` only when supported by source validation.
- [ ] Any mapping override risk is documented with reason and actor.

## 7. Rule Change Log

Add one row per rule-impacting change.

| Date (YYYY-MM-DD) | Area | Files Changed | Source Citation | Tests Added/Updated | Reviewer |
|---|---|---|---|---|---|
|  |  |  |  |  |  |
