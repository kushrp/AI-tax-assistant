# FreeTaxUSA Mapping Spec (Tax Year 2025)

## Purpose
Versioned source of truth for mapping canonical internal tax facts to FreeTaxUSA entry fields.

## Version
- Mapping pack: `freetaxusa_2025`
- Last validated date: `YYYY-MM-DD`
- Owner: `Agent F`
- Reviewer: `Agent D`

## Mapping Entry Template
Use one row per FreeTaxUSA target field.

| free_tax_usa_section | free_tax_usa_screen_path | export_field_key | canonical_fact_ref | data_type | format_rules | required_if | conditional_visibility | evidence_required | validation_rule | status |
|---|---|---|---|---|---|---|---|---|---|---|
| Income | Federal > Wages > W-2 Summary | federal.wages | 1040.line1a.wages | number | USD, 2 decimals | Always if W-2 present | Visible when W-2 flow enabled | W-2 PDF/CSV official | equals sum of W-2 box 1 values | verified |

## Scenario Coverage Matrix
- [ ] W-2 only
- [ ] W-2 + 1099-INT/1099-DIV
- [ ] 1099-B capital gains/losses
- [ ] Backdoor Roth conversion + prior-year 8606
- [ ] Crypto summaries
- [ ] Federal + NY state flow

## Drift Checks
- If a FreeTaxUSA field location/behavior changes:
  - Mark affected rows as `unverified`
  - Add note in `change_log`
  - Open blocking QA issue

## Change Log
| date | changed_by | summary | impacted_sections |
|---|---|---|---|
