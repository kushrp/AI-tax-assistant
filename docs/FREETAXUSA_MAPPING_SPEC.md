# FreeTaxUSA Mapping Spec (Tax Year 2025)

## Purpose
Versioned source of truth for mapping canonical tax facts to FreeTaxUSA field keys.

## Version
- Mapping pack: `freetaxusa_2025`
- Last validated date: `2026-03-04`
- Owner: `Agent F`
- Reviewer: `Agent D`

## Mapping Entries

| canonical_fact_ref | export_field_key | free_tax_usa_section | free_tax_usa_screen_path | data_type | format_rules | required_if | evidence_required | status |
|---|---|---|---|---|---|---|---|---|
| `1040.line1a.wages` | `federal.wages` | Income | Federal > Wages > W-2 Summary | number | USD, 2 decimals | W-2 exists | official W-2 evidence | verified |
| `1040.line2b.taxable_interest` | `federal.taxable_interest` | Income | Federal > Interest and Dividends > Interest | number | USD, 2 decimals | 1099-INT exists | official 1099-INT evidence | verified |
| `1040.line3a.qualified_dividends` | `federal.qualified_dividends` | Income | Federal > Interest and Dividends > Dividends | number | USD, 2 decimals | 1099-DIV exists | official 1099-DIV evidence | verified |
| `1040.line3b.ordinary_dividends` | `federal.ordinary_dividends` | Income | Federal > Interest and Dividends > Dividends | number | USD, 2 decimals | 1099-DIV exists | official 1099-DIV evidence | verified |
| `1040.line4a.ira_distributions` | `federal.ira_distributions` | Income | Federal > Retirement Income > IRA | number | USD, 2 decimals | 1099-R exists | 1099-R evidence | verified |
| `1040.line4b.taxable_ira` | `federal.taxable_ira` | Income | Federal > Retirement Income > IRA Taxable | number | USD, 2 decimals | IRA taxable value present | 1099-R + basis continuity | verified |
| `1040.line25a.withholding` | `federal.withholding` | Payments | Federal > Payments and Withholding | number | USD, 2 decimals | withholding exists | W-2/1099 withholding evidence | verified |
| `schedule_a.mortgage_interest` | `deductions.mortgage_interest` | Deductions | Federal > Itemized Deductions > Mortgage Interest | number | USD, 2 decimals | itemizing | Form 1098 evidence | verified |
| `schedule_a.property_tax` | `deductions.property_tax` | Deductions | Federal > Itemized Deductions > Taxes Paid | number | USD, 2 decimals | itemizing | tax payment evidence | verified |
| `schedule_a.charity` | `deductions.charity` | Deductions | Federal > Itemized Deductions > Charity | number | USD, 2 decimals | itemizing | donation receipts | verified |
| `schedule_a.medical` | `deductions.medical` | Deductions | Federal > Itemized Deductions > Medical Expenses | number | USD, 2 decimals | itemizing | medical payment evidence | verified |
| `schedule_1.student_loan_interest` | `adjustments.student_loan_interest` | Adjustments | Federal > Adjustments > Student Loan Interest | number | USD, 2 decimals | 1098-E exists | 1098-E evidence | verified |
| `schedule_d.total_proceeds` | `investments.total_proceeds` | Investments | Federal > Investments > Capital Gains | number | USD, 2 decimals | gains/losses exist | 1099-B/crypto statements | verified |
| `schedule_d.total_basis` | `investments.total_basis` | Investments | Federal > Investments > Capital Gains | number | USD, 2 decimals | gains/losses exist | 1099-B/crypto statements | verified |
| `schedule_d.net_capital_gain` | `investments.net_capital_gain` | Investments | Federal > Investments > Summary | number | USD, 2 decimals | net gain present | broker summary evidence | verified |
| `schedule_d.net_capital_loss` | `investments.net_capital_loss` | Investments | Federal > Investments > Summary | number | USD, 2 decimals | net loss present | broker summary evidence | verified |
| `schedule_d.capital_loss_carryover` | `investments.capital_loss_carryover` | Investments | Federal > Investments > Carryover | number | USD, 2 decimals | carryover exists | prior-year return evidence | verified |
| `roth.conversion.amount` | `retirement.roth_conversion` | Retirement | Federal > Retirement Income > IRA Conversion | number | USD, 2 decimals | Roth conversion exists | 1099-R + 5498 + prior-year 8606 | verified |
| `ny.it201.line1.wages` | `state.ny.wages` | State (NY) | State > New York > Income | number | USD, 2 decimals | primary state is NY | NY IT-201 / NY wage support | verified |
| `ny.it201.line33.new_york_adjusted_gross_income` | `state.ny.adjusted_gross_income` | State (NY) | State > New York > Income Summary | number | USD, 2 decimals | primary state is NY | NY IT-201 AGI support | verified |
| `ny.it201.line37.new_york_taxable_income` | `state.ny.taxable_income` | State (NY) | State > New York > Taxable Income | number | USD, 2 decimals | primary state is NY | NY IT-201 taxable income support | verified |
| `ny.it201.line46.new_york_state_tax` | `state.ny.tax` | State (NY) | State > New York > Tax Calculation | number | USD, 2 decimals | NY tax computed | NY IT-201 tax computation support | verified |
| `ny.it201.line61.new_york_state_withholding` | `state.ny.withholding` | State (NY) | State > New York > Payments and Credits | number | USD, 2 decimals | NY withholding exists | W-2/IT-2 or NY withholding support | verified |

## Drift Workflow
1. Identify drift or uncertainty in a row.
2. Set row status to `unverified` via API:
   - `POST /v1/mappings/freetaxusa/overrides`
3. System opens blocking issue:
   - `system.export.unverified_mapping_fields`
4. Revalidate row and set back to `verified`.
5. Export gate opens only when no unverified/unmapped material mappings remain.

## Scenario Coverage Matrix
- [x] W-2 only
- [x] W-2 + 1099-INT/1099-DIV
- [x] 1099-B capital gains/losses (multi-broker)
- [x] Backdoor Roth conversion + prior-year 8606
- [x] Crypto summaries (multi-exchange)
- [x] Federal + NY state flow

## Change Log
| date | changed_by | summary | impacted_sections |
|---|---|---|---|
| 2026-03-04 | codex | Added concrete field rows, drift workflow, and scenario validation status | income, deductions, investments, retirement |
| 2026-03-04 | codex | Added NY IT-201 mapping rows and validated federal + NY scenario coverage | state (NY), scenario matrix |
