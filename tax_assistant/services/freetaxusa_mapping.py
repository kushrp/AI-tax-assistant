from __future__ import annotations

FREETAXUSA_FIELD_MAP: dict[str, str] = {
    "1040.line1a.wages": "federal.wages",
    "1040.line2b.taxable_interest": "federal.taxable_interest",
    "1040.line3a.qualified_dividends": "federal.qualified_dividends",
    "1040.line3b.ordinary_dividends": "federal.ordinary_dividends",
    "1040.line4a.ira_distributions": "federal.ira_distributions",
    "1040.line4b.taxable_ira": "federal.taxable_ira",
    "1040.line25a.withholding": "federal.withholding",
    "schedule_a.mortgage_interest": "deductions.mortgage_interest",
    "schedule_a.property_tax": "deductions.property_tax",
    "schedule_a.charity": "deductions.charity",
    "schedule_a.medical": "deductions.medical",
    "schedule_1.student_loan_interest": "adjustments.student_loan_interest",
    "schedule_d.total_proceeds": "investments.total_proceeds",
    "schedule_d.total_basis": "investments.total_basis",
    "schedule_d.net_capital_gain": "investments.net_capital_gain",
    "schedule_d.net_capital_loss": "investments.net_capital_loss",
    "schedule_d.capital_loss_carryover": "investments.capital_loss_carryover",
    "roth.conversion.amount": "retirement.roth_conversion",
}


def mapped_field_key(form_line_ref: str) -> str | None:
    return FREETAXUSA_FIELD_MAP.get(form_line_ref)


def is_mapped_form_line_ref(form_line_ref: str) -> bool:
    return form_line_ref in FREETAXUSA_FIELD_MAP
