from __future__ import annotations

import json
import re

from sqlmodel import Session, select

from tax_assistant.models import (
    ApprovalEvent,
    Attestation,
    Document,
    FactStatus,
    FilingStatus,
    Issue,
    IssueStatus,
    Materiality,
    OptimizationScenario,
    TaxFact,
    TaxReturn,
)


_INCOME_REFS = {
    "1040.line1a.wages",
    "1040.line2b.taxable_interest",
    "1040.line3b.ordinary_dividends",
    "1040.line4b.taxable_ira",
    "schedule_d.net_capital_gain",
    "schedule_d.net_capital_loss",
}

_ITEMIZED_REFS = {
    "schedule_a.mortgage_interest",
    "schedule_a.property_tax",
    "schedule_a.charity",
    "schedule_a.medical",
}

_STANDARD_DEDUCTION = {
    FilingStatus.SINGLE: 15000.0,
    FilingStatus.MFJ: 30000.0,
    FilingStatus.MFS: 15000.0,
    FilingStatus.HOH: 22000.0,
}


def generate_scenarios(session: Session, return_id: str, include_itemized: bool = True) -> list[OptimizationScenario]:
    tax_return = _require_return(session, return_id)

    existing = list(session.exec(select(OptimizationScenario).where(OptimizationScenario.return_id == return_id)))
    for scenario in existing:
        session.delete(scenario)
    session.commit()

    facts = list(session.exec(select(TaxFact).where(TaxFact.return_id == return_id)))
    docs = list(session.exec(select(Document).where(Document.return_id == return_id)))
    open_issues = list(
        session.exec(select(Issue).where(Issue.return_id == return_id, Issue.status == IssueStatus.OPEN))
    )
    attestations = list(session.exec(select(Attestation).where(Attestation.return_id == return_id)))

    sums = _aggregate_facts(facts)

    filing_status = tax_return.filing_status
    standard = _STANDARD_DEDUCTION[filing_status]
    income_total = sums["income"]
    withholding = sums["withholding"]
    itemized_total = sums["itemized"]

    baseline_taxable = max(0.0, income_total - standard)
    baseline_tax = _estimate_federal_tax(baseline_taxable, filing_status)
    baseline_due = baseline_tax - withholding

    scenarios: list[OptimizationScenario] = []

    standard_required_evidence = ["w2", "1099 income statements", "withholding support"]
    scenarios.append(
        OptimizationScenario(
            return_id=return_id,
            name="standard_deduction",
            assumptions_json=json.dumps(
                {
                    "deduction_strategy": "standard",
                    "deduction_value": standard,
                    "taxable_income": baseline_taxable,
                }
            ),
            tax_outcome=round(baseline_due, 2),
            savings_delta=0.0,
            risk_score=_risk_score(
                open_issues,
                attestations,
                docs,
                facts,
                standard_required_evidence,
                scenario_complexity=0.0,
            ),
            required_evidence_json=json.dumps(standard_required_evidence),
        )
    )

    if include_itemized:
        itemized_required_evidence = ["1098", "property tax records", "charitable receipts"]
        deduction = max(standard, itemized_total)
        taxable = max(0.0, income_total - deduction)
        tax = _estimate_federal_tax(taxable, filing_status)
        due = tax - withholding
        scenarios.append(
            OptimizationScenario(
                return_id=return_id,
                name="itemized_deduction" if itemized_total > standard else "itemized_not_beneficial",
                assumptions_json=json.dumps(
                    {
                        "deduction_strategy": "itemized",
                        "itemized_value": round(itemized_total, 2),
                        "deduction_used": round(deduction, 2),
                        "taxable_income": round(taxable, 2),
                    }
                ),
                tax_outcome=round(due, 2),
                savings_delta=round(baseline_due - due, 2),
                risk_score=_risk_score(
                    open_issues,
                    attestations,
                    docs,
                    facts,
                    itemized_required_evidence,
                    scenario_complexity=0.04,
                ),
                required_evidence_json=json.dumps(itemized_required_evidence),
            )
        )

    has_roth_conversion = sums["roth_conversion"] > 0
    has_8606 = any(doc.doc_type == "8606" for doc in docs)
    if has_roth_conversion:
        roth_required_evidence = ["1099-r", "5498", "8606 (prior year)"]
        adjusted_income = income_total
        assumption = "roth_conversion_taxable"
        if has_8606:
            adjusted_income = max(0.0, income_total - sums["taxable_ira"])
            assumption = "backdoor_roth_basis_applied"

        taxable = max(0.0, adjusted_income - standard)
        tax = _estimate_federal_tax(taxable, filing_status)
        due = tax - withholding
        scenarios.append(
            OptimizationScenario(
                return_id=return_id,
                name="roth_conversion_handling",
                assumptions_json=json.dumps(
                    {
                        "roth_assumption": assumption,
                        "conversion_amount": sums["roth_conversion"],
                        "taxable_income": round(taxable, 2),
                    }
                ),
                tax_outcome=round(due, 2),
                savings_delta=round(baseline_due - due, 2),
                risk_score=_risk_score(
                    open_issues,
                    attestations,
                    docs,
                    facts,
                    roth_required_evidence,
                    scenario_complexity=0.08,
                ),
                required_evidence_json=json.dumps(roth_required_evidence),
            )
        )

    if len(scenarios) < 2 and _enough_facts_for_multi_scenario(facts):
        evidence_first_required = [*standard_required_evidence, "source evidence annotations"]
        scenarios.append(
            OptimizationScenario(
                return_id=return_id,
                name="evidence_first_standard",
                assumptions_json=json.dumps(
                    {
                        "deduction_strategy": "standard",
                        "documentation_posture": "evidence_first_review",
                        "taxable_income": baseline_taxable,
                    }
                ),
                tax_outcome=round(baseline_due, 2),
                savings_delta=0.0,
                risk_score=_risk_score(
                    open_issues,
                    attestations,
                    docs,
                    facts,
                    evidence_first_required,
                    scenario_complexity=0.02,
                ),
                required_evidence_json=json.dumps(evidence_first_required),
            )
        )

    ranked = sorted(scenarios, key=lambda s: (s.tax_outcome, s.risk_score, s.name))
    for idx, scenario in enumerate(ranked, start=1):
        scenario.rank = idx
        session.add(scenario)

    session.commit()

    stored = list(session.exec(select(OptimizationScenario).where(OptimizationScenario.return_id == return_id)))
    return sorted(stored, key=lambda s: s.rank)


def create_attestation(session: Session, return_id: str, fact_id: str, actor_id: str, rationale: str) -> Attestation:
    _require_return(session, return_id)
    fact = session.get(TaxFact, fact_id)
    if not fact or fact.return_id != return_id:
        raise ValueError("Invalid fact_id for this return")

    normalized_rationale = rationale.strip()
    if len(normalized_rationale) < 5:
        raise ValueError("Rationale must be at least 5 non-space characters")

    attestation = Attestation(return_id=return_id, fact_id=fact_id, actor_id=actor_id, rationale=normalized_rationale)
    session.add(attestation)

    # Human attestation promotes the fact into readiness coverage checks.
    if fact.materiality != Materiality.MATERIAL:
        fact.materiality = Materiality.MATERIAL
    fact.status = FactStatus.ATTESTED
    session.add(fact)

    session.commit()
    session.refresh(attestation)
    return attestation


def record_approval(session: Session, event: ApprovalEvent) -> ApprovalEvent:
    _require_return(session, event.return_id)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def approval_summary(session: Session, return_id: str) -> dict[str, str | None]:
    _require_return(session, return_id)
    events = list(
        session.exec(
            select(ApprovalEvent)
            .where(ApprovalEvent.return_id == return_id)
            .order_by(ApprovalEvent.created_at, ApprovalEvent.id)
        )
    )
    latest: dict[str, ApprovalEvent] = {}
    for event in events:
        latest[event.role.value] = event

    return {
        "taxpayer": latest.get("taxpayer").decision.value if latest.get("taxpayer") else None,
        "spouse": latest.get("spouse").decision.value if latest.get("spouse") else None,
        "cpa": latest.get("cpa").decision.value if latest.get("cpa") else None,
    }


def _aggregate_facts(facts: list[TaxFact]) -> dict[str, float]:
    values = {
        "income": 0.0,
        "withholding": 0.0,
        "itemized": 0.0,
        "roth_conversion": 0.0,
        "taxable_ira": 0.0,
    }

    for fact in facts:
        if fact.form_line_ref in _INCOME_REFS:
            values["income"] += fact.value
        if fact.form_line_ref == "1040.line25a.withholding":
            values["withholding"] += fact.value
        if fact.form_line_ref in _ITEMIZED_REFS:
            values["itemized"] += fact.value
        if fact.form_line_ref == "roth.conversion.amount":
            values["roth_conversion"] += fact.value
        if fact.form_line_ref == "1040.line4b.taxable_ira":
            values["taxable_ira"] += fact.value

    return values


def _estimate_federal_tax(taxable_income: float, filing_status: FilingStatus) -> float:
    if filing_status == FilingStatus.MFJ:
        brackets = [(23200, 0.1), (94300, 0.12), (201050, 0.22), (383900, 0.24), (487450, 0.32), (731200, 0.35)]
    else:
        brackets = [(11600, 0.1), (47150, 0.12), (100525, 0.22), (191950, 0.24), (243725, 0.32), (609350, 0.35)]

    remaining = taxable_income
    last_cap = 0.0
    tax = 0.0
    for cap, rate in brackets:
        if remaining <= 0:
            break
        taxable_at_rate = min(remaining, cap - last_cap)
        tax += taxable_at_rate * rate
        remaining -= taxable_at_rate
        last_cap = cap

    if remaining > 0:
        tax += remaining * 0.37

    return round(tax, 2)


def _risk_score(
    open_issues: list[Issue],
    attestations: list[Attestation],
    docs: list[Document],
    facts: list[TaxFact],
    required_evidence: list[str],
    scenario_complexity: float,
) -> float:
    blocking = sum(1 for issue in open_issues if issue.blocking)
    non_blocking = max(0, len(open_issues) - blocking)

    material_facts = [fact for fact in facts if fact.materiality == Materiality.MATERIAL]
    attested_ids = {att.fact_id for att in attestations}
    if material_facts:
        trusted_material = sum(
            1
            for fact in material_facts
            if fact.id in attested_ids or fact.status in {FactStatus.VERIFIED, FactStatus.ATTESTED}
        )
        unresolved_material_ratio = 1 - (trusted_material / len(material_facts))
    else:
        unresolved_material_ratio = 0.0

    supplemental_ratio = 0.0
    if facts:
        supplemental_doc_ids = {doc.id for doc in docs if doc.quality_tier.value == "supplemental"}
        supplemental_facts = [fact for fact in facts if fact.source_doc_id in supplemental_doc_ids]
        supplemental_ratio = len(supplemental_facts) / len(facts)

    missing_required_ratio = _missing_required_evidence_ratio(required_evidence, docs)

    base = 0.05
    score = (
        base
        + (blocking * 0.22)
        + (non_blocking * 0.03)
        + (unresolved_material_ratio * 0.25)
        + (supplemental_ratio * 0.2)
        + (missing_required_ratio * 0.2)
        + scenario_complexity
    )
    return round(min(1.0, max(0.0, score)), 2)


def _missing_required_evidence_ratio(required_evidence: list[str], docs: list[Document]) -> float:
    if not required_evidence:
        return 0.0

    searchable = _document_searchable_labels(docs)
    missing = sum(1 for evidence in required_evidence if not _evidence_requirement_present(evidence, searchable))
    return missing / len(required_evidence)


def _document_searchable_labels(docs: list[Document]) -> list[str]:
    labels: list[str] = []
    for doc in docs:
        labels.append(doc.doc_type.lower())
        labels.append(doc.file_name.lower())
    return labels


def _evidence_requirement_present(requirement: str, searchable_docs: list[str]) -> bool:
    if not searchable_docs:
        return False

    normalized = requirement.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) >= 2]
    if not tokens:
        return True
    return any(token in doc_text for token in tokens for doc_text in searchable_docs)


def _enough_facts_for_multi_scenario(facts: list[TaxFact]) -> bool:
    material_facts = [fact for fact in facts if fact.materiality == Materiality.MATERIAL]
    return len(material_facts) >= 2


def _require_return(session: Session, return_id: str) -> TaxReturn:
    tax_return = session.get(TaxReturn, return_id)
    if not tax_return:
        raise ValueError(f"Return '{return_id}' does not exist")
    return tax_return
