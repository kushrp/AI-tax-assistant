from __future__ import annotations

from collections import defaultdict

from sqlmodel import Session, col, select

from tax_assistant.models import (
    Attestation,
    Document,
    DocumentQuality,
    EvidenceLink,
    Issue,
    IssueSeverity,
    IssueStatus,
    Materiality,
    SourceType,
    TaxFact,
    TaxReturn,
)
from tax_assistant.services.freetaxusa_mapping import additive_form_line_refs, is_mapped_form_line_ref, is_verified_mapping


def refresh_system_issues(session: Session, return_id: str) -> list[Issue]:
    tax_return = session.get(TaxReturn, return_id)
    if not tax_return:
        raise ValueError(f"Return '{return_id}' does not exist")

    _clear_open_system_issues(session, return_id)

    facts = list(session.exec(select(TaxFact).where(TaxFact.return_id == return_id)))
    documents = list(session.exec(select(Document).where(Document.return_id == return_id)))
    attestations = list(session.exec(select(Attestation).where(Attestation.return_id == return_id)))
    fact_ids = [fact.id for fact in facts]
    evidence_links = (
        list(session.exec(select(EvidenceLink).where(EvidenceLink.fact_id.in_(fact_ids))))
        if fact_ids
        else []
    )

    issues: list[Issue] = []
    issues.extend(_conflicting_values_issues(return_id, facts))
    issues.extend(_missing_8606_issues(return_id, tax_return.tax_year, facts, documents))
    issues.extend(_screenshot_only_evidence_issues(return_id, facts, documents, evidence_links))
    issues.extend(_low_confidence_material_issues(return_id, facts, attestations))
    issues.extend(_unmapped_or_unverified_material_fact_issues(session, return_id, facts))
    issues.extend(_missing_material_evidence_issues(return_id, facts, attestations, evidence_links))

    for issue in issues:
        session.add(issue)

    session.commit()

    return list(session.exec(select(Issue).where(Issue.return_id == return_id, Issue.status == IssueStatus.OPEN)))


def _clear_open_system_issues(session: Session, return_id: str) -> None:
    system_issues = list(
        session.exec(
            select(Issue).where(
                Issue.return_id == return_id,
                col(Issue.category).startswith("system."),
                Issue.status == IssueStatus.OPEN,
            )
        )
    )
    for issue in system_issues:
        session.delete(issue)
    session.commit()


def _conflicting_values_issues(return_id: str, facts: list[TaxFact]) -> list[Issue]:
    aggregatable = additive_form_line_refs()
    by_ref: dict[str, set[float]] = defaultdict(set)
    for fact in facts:
        if fact.materiality != Materiality.MATERIAL:
            continue
        if fact.form_line_ref in aggregatable:
            continue
        by_ref[fact.form_line_ref].add(round(fact.value, 2))

    issues: list[Issue] = []
    for ref, values in by_ref.items():
        if len(values) <= 1:
            continue
        sorted_values = ", ".join(str(v) for v in sorted(values))
        issues.append(
            Issue(
                return_id=return_id,
                severity=IssueSeverity.HIGH,
                category="system.conflict.values",
                title=f"Conflicting values for {ref}",
                description=f"Multiple extracted values detected for {ref}: {sorted_values}.",
                blocking=True,
                recommended_action="Review source documents and keep one authoritative value.",
            )
        )

    return issues


def _screenshot_only_evidence_issues(
    return_id: str,
    facts: list[TaxFact],
    documents: list[Document],
    evidence_links: list[EvidenceLink],
) -> list[Issue]:
    doc_map = {d.id: d for d in documents}
    evidence_doc_ids_by_fact: dict[str, set[str]] = defaultdict(set)
    for link in evidence_links:
        evidence_doc_ids_by_fact[link.fact_id].add(link.doc_id)

    doc_ids_by_ref: dict[str, set[str]] = defaultdict(set)
    for fact in facts:
        if fact.materiality != Materiality.MATERIAL:
            continue
        doc_ids_by_ref[fact.form_line_ref].update(evidence_doc_ids_by_fact.get(fact.id, set()))
        if fact.source_doc_id:
            doc_ids_by_ref[fact.form_line_ref].add(fact.source_doc_id)

    refs: set[str] = set()
    for ref, doc_ids in doc_ids_by_ref.items():
        supporting_docs = [doc_map[doc_id] for doc_id in doc_ids if doc_id in doc_map]
        if not supporting_docs:
            continue
        if all(_is_supplemental_evidence(doc) for doc in supporting_docs):
            refs.add(ref)

    if not refs:
        return []

    refs_str = ", ".join(sorted(refs))
    return [
        Issue(
            return_id=return_id,
            severity=IssueSeverity.HIGH,
            category="system.evidence.supplemental_only",
            title="Material fields supported only by screenshots/photos",
            description=f"Material fields are supported only by screenshot/photo evidence: {refs_str}.",
            blocking=True,
            recommended_action="Upload official PDF/CSV statements for all listed fields.",
        )
    ]


def _missing_8606_issues(
    return_id: str,
    current_tax_year: int,
    facts: list[TaxFact],
    documents: list[Document],
) -> list[Issue]:
    roth_signal = any(
        f.form_line_ref in {"roth.conversion.amount", "1040.line4a.ira_distributions", "1040.line4b.taxable_ira"}
        and f.value > 0
        for f in facts
    )

    if not roth_signal:
        return []

    has_prior_8606 = any(_is_prior_year_8606_document(doc, current_tax_year) for doc in documents)
    if has_prior_8606:
        return []

    return [
        Issue(
            return_id=return_id,
            severity=IssueSeverity.CRITICAL,
            category="system.backdoor_roth.missing_8606",
            title="Missing prior-year Form 8606",
            description="Backdoor Roth/IRA conversion signals were found, but no prior-year Form 8606 was provided.",
            blocking=True,
            recommended_action="Upload prior-year Form 8606 to validate nondeductible basis continuity.",
        )
    ]


def _low_confidence_material_issues(return_id: str, facts: list[TaxFact], attestations: list[Attestation]) -> list[Issue]:
    attested_fact_ids = {a.fact_id for a in attestations}
    low_confidence_refs = [
        fact.form_line_ref
        for fact in facts
        if fact.materiality == Materiality.MATERIAL and fact.confidence < 0.8 and fact.id not in attested_fact_ids
    ]

    if not low_confidence_refs:
        return []

    refs = ", ".join(sorted(set(low_confidence_refs)))
    return [
        Issue(
            return_id=return_id,
            severity=IssueSeverity.HIGH,
            category="system.evidence.low_confidence",
            title="Low confidence material facts",
            description=f"Material fields below confidence threshold without attestation: {refs}.",
            blocking=True,
            recommended_action="Upload clearer source docs or attest each affected value with rationale.",
        )
    ]


def _missing_material_evidence_issues(
    return_id: str,
    facts: list[TaxFact],
    attestations: list[Attestation],
    evidence_links: list[EvidenceLink],
) -> list[Issue]:
    attested_fact_ids = {a.fact_id for a in attestations}
    covered_fact_ids = {link.fact_id for link in evidence_links}
    missing = [
        fact.form_line_ref
        for fact in facts
        if fact.materiality == Materiality.MATERIAL
        and fact.id not in attested_fact_ids
        and fact.id not in covered_fact_ids
    ]

    if not missing:
        return []

    refs = ", ".join(sorted(set(missing)))
    return [
        Issue(
            return_id=return_id,
            severity=IssueSeverity.HIGH,
            category="system.evidence.missing_coverage",
            title="Missing evidence coverage for material facts",
            description=f"Material facts have no evidence coverage and no attestation: {refs}.",
            blocking=True,
            recommended_action="Attach evidence or provide an attestation rationale for each listed field.",
        )
    ]


def _unmapped_or_unverified_material_fact_issues(
    session: Session,
    return_id: str,
    facts: list[TaxFact],
) -> list[Issue]:
    unmapped_refs = sorted(
        {
            fact.form_line_ref
            for fact in facts
            if fact.materiality == Materiality.MATERIAL and not is_mapped_form_line_ref(fact.form_line_ref)
        }
    )
    unverified_refs = sorted(
        {
            fact.form_line_ref
            for fact in facts
            if fact.materiality == Materiality.MATERIAL
            and is_mapped_form_line_ref(fact.form_line_ref)
            and not is_verified_mapping(session, fact.form_line_ref)
        }
    )

    issues: list[Issue] = []
    if unmapped_refs:
        refs = ", ".join(unmapped_refs)
        issues.append(
            Issue(
                return_id=return_id,
                severity=IssueSeverity.CRITICAL,
                category="system.export.unmapped_material_fields",
                title="Material facts missing FreeTaxUSA mapping",
                description=f"Material facts cannot be exported because they are unmapped: {refs}.",
                blocking=True,
                recommended_action="Map each listed form line to a FreeTaxUSA field key or mark it non-material.",
            )
        )
    if unverified_refs:
        refs = ", ".join(unverified_refs)
        issues.append(
            Issue(
                return_id=return_id,
                severity=IssueSeverity.CRITICAL,
                category="system.export.unverified_mapping_fields",
                title="Material facts mapped to unverified FreeTaxUSA fields",
                description=f"Material facts map to unverified fields and must be revalidated: {refs}.",
                blocking=True,
                recommended_action="Review mapping pack and mark impacted rows verified before export.",
            )
        )

    return issues


def _is_supplemental_evidence(document: Document) -> bool:
    return document.quality_tier == DocumentQuality.SUPPLEMENTAL or document.source_type in {
        SourceType.SCREENSHOT,
        SourceType.PHOTO,
    }


def _is_prior_year_8606_document(document: Document, current_tax_year: int) -> bool:
    if document.tax_year >= current_tax_year:
        return False

    if document.doc_type == "8606":
        return True

    return "8606" in document.file_name.lower()
