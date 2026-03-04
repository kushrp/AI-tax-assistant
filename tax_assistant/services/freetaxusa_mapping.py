from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from tax_assistant.models import MappingOverride, MappingStatus

MAPPING_PACK_VERSION = "freetaxusa_2025"


@dataclass(frozen=True)
class MappingEntry:
    canonical_fact_ref: str
    export_field_key: str
    default_status: MappingStatus = MappingStatus.VERIFIED
    verification_note: str | None = None
    additive: bool = False


_MAPPING_ENTRIES: tuple[MappingEntry, ...] = (
    MappingEntry("1040.line1a.wages", "federal.wages"),
    MappingEntry("1040.line2b.taxable_interest", "federal.taxable_interest"),
    MappingEntry("1040.line3a.qualified_dividends", "federal.qualified_dividends"),
    MappingEntry("1040.line3b.ordinary_dividends", "federal.ordinary_dividends"),
    MappingEntry("1040.line4a.ira_distributions", "federal.ira_distributions"),
    MappingEntry("1040.line4b.taxable_ira", "federal.taxable_ira"),
    MappingEntry("1040.line25a.withholding", "federal.withholding"),
    MappingEntry("schedule_a.mortgage_interest", "deductions.mortgage_interest"),
    MappingEntry("schedule_a.property_tax", "deductions.property_tax"),
    MappingEntry("schedule_a.charity", "deductions.charity"),
    MappingEntry("schedule_a.medical", "deductions.medical"),
    MappingEntry("schedule_1.student_loan_interest", "adjustments.student_loan_interest"),
    MappingEntry("schedule_d.total_proceeds", "investments.total_proceeds", additive=True),
    MappingEntry("schedule_d.total_basis", "investments.total_basis", additive=True),
    MappingEntry("schedule_d.net_capital_gain", "investments.net_capital_gain"),
    MappingEntry("schedule_d.net_capital_loss", "investments.net_capital_loss"),
    MappingEntry("schedule_d.capital_loss_carryover", "investments.capital_loss_carryover"),
    MappingEntry("roth.conversion.amount", "retirement.roth_conversion"),
    MappingEntry("ny.it201.line1.wages", "state.ny.wages"),
    MappingEntry("ny.it201.line33.new_york_adjusted_gross_income", "state.ny.adjusted_gross_income"),
    MappingEntry("ny.it201.line37.new_york_taxable_income", "state.ny.taxable_income"),
    MappingEntry("ny.it201.line46.new_york_state_tax", "state.ny.tax"),
    MappingEntry("ny.it201.line61.new_york_state_withholding", "state.ny.withholding"),
)

_ENTRY_BY_REF = {entry.canonical_fact_ref: entry for entry in _MAPPING_ENTRIES}


def mapped_field_key(
    session: Session,
    form_line_ref: str,
    *,
    include_unverified: bool = False,
) -> str | None:
    entry = _ENTRY_BY_REF.get(form_line_ref)
    if not entry:
        return None
    status = effective_mapping_status(session, form_line_ref)
    if status != MappingStatus.VERIFIED and not include_unverified:
        return None
    return entry.export_field_key


def is_mapped_form_line_ref(form_line_ref: str) -> bool:
    return form_line_ref in _ENTRY_BY_REF


def is_verified_mapping(session: Session, form_line_ref: str) -> bool:
    entry = _ENTRY_BY_REF.get(form_line_ref)
    if not entry:
        return False
    return effective_mapping_status(session, form_line_ref) == MappingStatus.VERIFIED


def effective_mapping_status(session: Session, form_line_ref: str) -> MappingStatus:
    entry = _ENTRY_BY_REF.get(form_line_ref)
    if not entry:
        raise ValueError(f"Unknown canonical fact reference '{form_line_ref}'")
    latest = _latest_override(session, form_line_ref)
    if latest:
        return latest.status
    return entry.default_status


def effective_mapping_rows(session: Session) -> list[dict]:
    overrides = _latest_overrides_by_ref(session)
    rows: list[dict] = []
    for entry in sorted(_MAPPING_ENTRIES, key=lambda item: item.canonical_fact_ref):
        override = overrides.get(entry.canonical_fact_ref)
        rows.append(
            {
                "pack_version": MAPPING_PACK_VERSION,
                "canonical_fact_ref": entry.canonical_fact_ref,
                "export_field_key": entry.export_field_key,
                "status": (override.status if override else entry.default_status).value,
                "verification_note": override.reason if override else entry.verification_note,
                "updated_by": override.updated_by if override else None,
                "updated_at": override.updated_at if override else None,
            }
        )
    return rows


def set_mapping_override(
    session: Session,
    *,
    canonical_fact_ref: str,
    status: MappingStatus,
    actor_id: str,
    reason: str | None = None,
) -> MappingOverride:
    if canonical_fact_ref not in _ENTRY_BY_REF:
        raise ValueError(f"Unknown canonical fact reference '{canonical_fact_ref}'")

    override = MappingOverride(
        pack_version=MAPPING_PACK_VERSION,
        canonical_fact_ref=canonical_fact_ref,
        status=status,
        reason=(reason or "").strip() or None,
        updated_by=actor_id,
    )
    session.add(override)
    session.commit()
    session.refresh(override)
    return override


def additive_field_keys() -> set[str]:
    return {entry.export_field_key for entry in _MAPPING_ENTRIES if entry.additive}


def additive_form_line_refs() -> set[str]:
    return {entry.canonical_fact_ref for entry in _MAPPING_ENTRIES if entry.additive}


def _latest_override(session: Session, canonical_fact_ref: str) -> MappingOverride | None:
    return (
        session.exec(
            select(MappingOverride)
            .where(
                MappingOverride.pack_version == MAPPING_PACK_VERSION,
                MappingOverride.canonical_fact_ref == canonical_fact_ref,
            )
            .order_by(MappingOverride.updated_at.desc(), MappingOverride.id.desc())
        )
        .first()
    )


def _latest_overrides_by_ref(session: Session) -> dict[str, MappingOverride]:
    overrides = list(
        session.exec(
            select(MappingOverride)
            .where(MappingOverride.pack_version == MAPPING_PACK_VERSION)
            .order_by(MappingOverride.updated_at, MappingOverride.id)
        )
    )
    latest: dict[str, MappingOverride] = {}
    for override in overrides:
        latest[override.canonical_fact_ref] = override
    return latest
