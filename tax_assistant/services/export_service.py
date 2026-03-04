from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlmodel import Session, select

from tax_assistant.config import Settings
from tax_assistant.models import ApprovalEvent, EvidenceLink, Issue, IssueStatus, TaxFact, TaxReturn
from tax_assistant.services.freetaxusa_mapping import mapped_field_key
from tax_assistant.services.confidence_service import evaluate_readiness
from tax_assistant.services.rules_engine import refresh_system_issues


def build_freetaxusa_export(session: Session, settings: Settings, return_id: str) -> dict:
    tax_return = session.get(TaxReturn, return_id)
    if not tax_return:
        raise HTTPException(status_code=404, detail="Return not found")

    refresh_system_issues(session, return_id)
    readiness = evaluate_readiness(session, settings, return_id)

    if not readiness.ready_to_file:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Return is not ready to file",
                "readiness": readiness.__dict__,
            },
        )

    facts = list(session.exec(select(TaxFact).where(TaxFact.return_id == return_id)))
    links = list(session.exec(select(EvidenceLink).where(EvidenceLink.fact_id.in_([fact.id for fact in facts]))))
    issues = list(session.exec(select(Issue).where(Issue.return_id == return_id, Issue.status == IssueStatus.OPEN)))
    approvals = list(session.exec(select(ApprovalEvent).where(ApprovalEvent.return_id == return_id)))

    links_by_fact: dict[str, list[EvidenceLink]] = {}
    for link in links:
        links_by_fact.setdefault(link.fact_id, []).append(link)

    mapped_facts: dict[str, list[TaxFact]] = {}
    evidence_report: dict[str, list[dict]] = {}

    for fact in facts:
        field_key = mapped_field_key(fact.form_line_ref)
        if not field_key:
            continue

        mapped_facts.setdefault(field_key, []).append(fact)
        evidence_report.setdefault(field_key, []).append(
            {
                "fact_id": fact.id,
                "doc_id": fact.source_doc_id,
                "locator": fact.source_locator,
                "confidence": fact.confidence,
                "form_line_ref": fact.form_line_ref,
                "evidence_links": [
                    {
                        "id": link.id,
                        "method": link.extraction_method,
                        "page": link.page,
                        "checksum": link.checksum,
                    }
                    for link in links_by_fact.get(fact.id, [])
                ],
            }
        )

    fields: list[dict] = []
    for field_key in sorted(mapped_facts):
        candidates = sorted(mapped_facts[field_key], key=lambda fact: (fact.confidence, fact.created_at), reverse=True)
        canonical = candidates[0]
        fields.append(
            {
                "field_key": field_key,
                "value": round(canonical.value, 2),
                "fact_id": canonical.id,
                "source_doc_id": canonical.source_doc_id,
                "confidence": canonical.confidence,
            }
        )
        evidence_report[field_key] = sorted(
            evidence_report.get(field_key, []),
            key=lambda entry: (entry["confidence"], entry["fact_id"]),
            reverse=True,
        )

    unresolved = [issue.title for issue in sorted(issues, key=lambda item: item.created_at)]
    audit_summary = _build_audit_summary(approvals)

    return {
        "return_id": return_id,
        "tax_year": tax_return.tax_year,
        "generated_at": datetime.now(timezone.utc),
        "ready_to_file": readiness.ready_to_file,
        "fields": fields,
        "unresolved_question_queue": unresolved,
        "evidence_report": evidence_report,
        "audit_summary": audit_summary,
    }


def _build_audit_summary(approvals: list[ApprovalEvent]) -> dict:
    latest_by_role: dict[str, dict] = {}
    for event in sorted(approvals, key=lambda item: item.created_at):
        latest_by_role[event.role.value] = {
            "decision": event.decision.value,
            "actor_id": event.actor_id,
            "timestamp": event.created_at.isoformat(),
            "notes": event.notes,
        }

    return {
        "approvals": latest_by_role,
        "approval_events": [
            {
                "id": event.id,
                "role": event.role.value,
                "decision": event.decision.value,
                "actor_id": event.actor_id,
                "created_at": event.created_at.isoformat(),
                "notes": event.notes,
            }
            for event in sorted(approvals, key=lambda item: item.created_at)
        ],
    }
