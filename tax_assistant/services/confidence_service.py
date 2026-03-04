from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from tax_assistant.config import Settings
from tax_assistant.models import Attestation, EvidenceLink, Issue, IssueStatus, Materiality, TaxFact


@dataclass
class ReadinessSummary:
    ready_to_file: bool
    material_fields_total: int
    evidenced_or_attested: int
    evidence_coverage_pct: float
    open_blocking_issues: int
    blockers: list[str]


def evaluate_readiness(session: Session, settings: Settings, return_id: str) -> ReadinessSummary:
    _ = settings  # Reserved for future threshold tuning; readiness currently follows evidence/attestation coverage.
    material_facts = list(
        session.exec(
            select(TaxFact).where(
                TaxFact.return_id == return_id,
                TaxFact.materiality == Materiality.MATERIAL,
            )
        )
    )
    fact_ids = [fact.id for fact in material_facts]

    evidence_by_fact: dict[str, list[EvidenceLink]] = {}
    if fact_ids:
        links = list(session.exec(select(EvidenceLink).where(EvidenceLink.fact_id.in_(fact_ids))))
        for link in links:
            evidence_by_fact.setdefault(link.fact_id, []).append(link)

    attested_ids = {
        att.fact_id for att in session.exec(select(Attestation).where(Attestation.return_id == return_id))
    }

    covered = 0
    for fact in material_facts:
        has_evidence = bool(evidence_by_fact.get(fact.id))
        if has_evidence or fact.id in attested_ids:
            covered += 1

    total = len(material_facts)
    coverage = 100.0 if total == 0 else round((covered / total) * 100, 2)

    blocking_issues = list(
        session.exec(
            select(Issue).where(
                Issue.return_id == return_id,
                Issue.status == IssueStatus.OPEN,
                Issue.blocking.is_(True),
            )
        )
    )

    ready = total == covered and len(blocking_issues) == 0
    blocker_messages = sorted(issue.title for issue in blocking_issues)

    return ReadinessSummary(
        ready_to_file=ready,
        material_fields_total=total,
        evidenced_or_attested=covered,
        evidence_coverage_pct=coverage,
        open_blocking_issues=len(blocking_issues),
        blockers=blocker_messages,
    )
