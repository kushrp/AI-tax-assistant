## Summary

- What changed:
- Why:

## Tax Rule Consistency

- [ ] I reviewed [`docs/TAX_RULE_CONSISTENCY_CHECKLIST.md`](docs/TAX_RULE_CONSISTENCY_CHECKLIST.md).
- [ ] I classified tax-rule impact:
  - [ ] No tax-rule impact.
  - [ ] Tax-rule impacting change (sections 1-6 completed in checklist).
- [ ] For tax-rule impacting changes, I updated source citations and mapping documentation where needed.
- [ ] For tax-rule impacting changes, I updated/added regression tests.
- [ ] For tax-rule impacting changes, I updated the rule change log table in the checklist.
- [ ] I verified API/model contract compatibility for shared surfaces (`tax_assistant/models.py`, `tax_assistant/schemas.py`, `tax_assistant/api/routes.py`).

## Verification

- [ ] Local tests run (or CI-only by design)
- [ ] Relevant command(s) and results added below

```bash
# Example:
# python run_tests.py tests/test_service_logic.py::test_refresh_system_issues_is_idempotent_and_flags_missing_coverage
```

## Source Citations (Required For Tax-Rule Changes)

- Citation 1:
- Citation 2:

