from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from tax_assistant.config import Settings
from tax_assistant.models import (
    ApprovalEvent,
    Attestation,
    Document,
    EvidenceLink,
    ExtractionJob,
    Issue,
    OptimizationScenario,
    TaxFact,
    TaxReturn,
)
from tax_assistant.services.storage_service import build_object_storage


@dataclass
class RetentionResult:
    returns_deleted: int = 0
    documents_deleted: int = 0
    facts_deleted: int = 0
    issues_deleted: int = 0
    extraction_jobs_deleted: int = 0
    evidences_deleted: int = 0
    attestations_deleted: int = 0
    approvals_deleted: int = 0
    scenarios_deleted: int = 0
    storage_objects_deleted: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def apply_retention_policy(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> RetentionResult:
    result = RetentionResult()
    retention_days = max(1, int(settings.retention_days))
    now_utc = now or datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=retention_days)

    old_returns = list(session.exec(select(TaxReturn).where(TaxReturn.created_at < cutoff)))
    if not old_returns:
        return result

    storage = build_object_storage(settings)

    for tax_return in old_returns:
        documents = list(session.exec(select(Document).where(Document.return_id == tax_return.id)))
        document_ids = [doc.id for doc in documents]
        facts = (
            list(session.exec(select(TaxFact).where(TaxFact.source_doc_id.in_(document_ids))))
            if document_ids
            else []
        )
        fact_ids = [fact.id for fact in facts]

        evidences = []
        if fact_ids:
            evidences.extend(list(session.exec(select(EvidenceLink).where(EvidenceLink.fact_id.in_(fact_ids)))))
        if document_ids:
            evidences.extend(list(session.exec(select(EvidenceLink).where(EvidenceLink.doc_id.in_(document_ids)))))
        # Preserve deletion idempotency in case evidence was selected by fact and doc criteria.
        evidence_by_id = {item.id: item for item in evidences}

        attestations = list(session.exec(select(Attestation).where(Attestation.return_id == tax_return.id)))
        approvals = list(session.exec(select(ApprovalEvent).where(ApprovalEvent.return_id == tax_return.id)))
        scenarios = list(session.exec(select(OptimizationScenario).where(OptimizationScenario.return_id == tax_return.id)))
        issues = list(session.exec(select(Issue).where(Issue.return_id == tax_return.id)))
        jobs = (
            list(session.exec(select(ExtractionJob).where(ExtractionJob.document_id.in_(document_ids))))
            if document_ids
            else []
        )

        for evidence in evidence_by_id.values():
            session.delete(evidence)
            result.evidences_deleted += 1
        for attestation in attestations:
            session.delete(attestation)
            result.attestations_deleted += 1
        for approval in approvals:
            session.delete(approval)
            result.approvals_deleted += 1
        for scenario in scenarios:
            session.delete(scenario)
            result.scenarios_deleted += 1
        for issue in issues:
            session.delete(issue)
            result.issues_deleted += 1
        for fact in facts:
            session.delete(fact)
            result.facts_deleted += 1
        for job in jobs:
            session.delete(job)
            result.extraction_jobs_deleted += 1

        for doc in documents:
            if storage.exists(doc.storage_path):
                storage.delete(doc.storage_path)
                result.storage_objects_deleted += 1
            session.delete(doc)
            result.documents_deleted += 1

        session.delete(tax_return)
        result.returns_deleted += 1

    session.commit()
    return result
