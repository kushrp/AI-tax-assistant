from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from tax_assistant.config import Settings
from tax_assistant.deps import get_actor_context, get_session, get_settings
from tax_assistant.models import ApprovalEvent, ApprovalRole, Document, Issue, IssueStatus, SourceType, TaxFact, TaxReturn
from tax_assistant.schemas import (
    ActorContext,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalSummary,
    AttestRequest,
    CreateReturnRequest,
    ExtractionResponse,
    FreetaxusaExportResponse,
    IssueResponse,
    OptimizeRequest,
    OptimizeResponse,
    OptimizationScenarioResponse,
    ReadinessResponse,
    ReturnResponse,
    TaxFactResponse,
    UploadResponse,
)
from tax_assistant.services.confidence_service import evaluate_readiness
from tax_assistant.services.document_service import upload_document
from tax_assistant.services.export_service import build_freetaxusa_export
from tax_assistant.services.extraction_service import run_extraction
from tax_assistant.services.optimization_service import approval_summary, create_attestation, generate_scenarios, record_approval
from tax_assistant.services.rules_engine import refresh_system_issues

router = APIRouter()


@router.post("/returns", response_model=ReturnResponse)
def create_return(payload: CreateReturnRequest, session: Session = Depends(get_session)) -> ReturnResponse:
    tax_return = TaxReturn(
        tax_year=payload.tax_year,
        primary_state=payload.primary_state,
        filing_status=payload.filing_status,
    )
    session.add(tax_return)
    session.commit()
    session.refresh(tax_return)
    return ReturnResponse(
        id=tax_return.id,
        tax_year=tax_return.tax_year,
        primary_state=tax_return.primary_state,
        filing_status=tax_return.filing_status.value,
        status=tax_return.status.value,
        created_at=tax_return.created_at,
    )


@router.post("/documents/upload", response_model=UploadResponse)
async def upload_document_route(
    return_id: Annotated[str, Form(...)],
    tax_year: Annotated[int, Form(...)],
    owner: Annotated[str, Form(...)],
    source_type: Annotated[str, Form(...)],
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    normalized_return_id = return_id.strip()
    normalized_owner = owner.strip() or "taxpayer"
    if not normalized_return_id:
        raise HTTPException(status_code=400, detail="return_id is required")

    try:
        source = SourceType(source_type.lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid source_type '{source_type}'") from exc

    try:
        result = await upload_document(
            session,
            settings,
            return_id=normalized_return_id,
            tax_year=tax_year,
            owner=normalized_owner,
            source_type=source,
            file=file,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return UploadResponse(
        document_id=result.document.id,
        classification_status=result.document.classification_status,
        doc_type=result.document.doc_type,
        duplicate=result.duplicate,
    )


@router.post("/documents/{document_id}/extract", response_model=ExtractionResponse)
def extract_document_route(document_id: str, session: Session = Depends(get_session)) -> ExtractionResponse:
    document = session.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        job, facts = run_extraction(session, document)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document file missing: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}") from exc

    issues = refresh_system_issues(session, document.return_id)

    return ExtractionResponse(
        extraction_job_id=job.id,
        document_id=document.id,
        extracted_facts=len(facts),
        issues_created=len(issues),
    )


@router.get("/returns/{return_id}/facts", response_model=list[TaxFactResponse])
def list_facts(return_id: str, session: Session = Depends(get_session)) -> list[TaxFactResponse]:
    facts = list(session.exec(select(TaxFact).where(TaxFact.return_id == return_id)))
    return [
        TaxFactResponse(
            id=f.id,
            return_id=f.return_id,
            tax_year=f.tax_year,
            form_line_ref=f.form_line_ref,
            value=f.value,
            raw_value=f.raw_value,
            source_doc_id=f.source_doc_id,
            source_locator=f.source_locator,
            confidence=f.confidence,
            materiality=f.materiality,
            status=f.status.value,
        )
        for f in facts
    ]


@router.get("/returns/{return_id}/issues", response_model=list[IssueResponse])
def list_issues(return_id: str, session: Session = Depends(get_session)) -> list[IssueResponse]:
    try:
        refresh_system_issues(session, return_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    issues = list(session.exec(select(Issue).where(Issue.return_id == return_id, Issue.status == IssueStatus.OPEN)))
    return [
        IssueResponse(
            id=i.id,
            severity=i.severity.value,
            category=i.category,
            title=i.title,
            description=i.description,
            blocking=i.blocking,
            recommended_action=i.recommended_action,
            owner=i.owner,
            status=i.status.value,
        )
        for i in issues
    ]


@router.get("/returns/{return_id}/readiness", response_model=ReadinessResponse)
def return_readiness(
    return_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReadinessResponse:
    try:
        refresh_system_issues(session, return_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    readiness = evaluate_readiness(session, settings, return_id)
    return ReadinessResponse(**readiness.__dict__)


@router.post("/returns/{return_id}/optimize", response_model=OptimizeResponse)
def optimize_return(
    return_id: str,
    payload: OptimizeRequest,
    session: Session = Depends(get_session),
) -> OptimizeResponse:
    try:
        refresh_system_issues(session, return_id)
        scenarios = generate_scenarios(session, return_id, include_itemized=payload.include_itemized)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return OptimizeResponse(
        scenarios=[
            OptimizationScenarioResponse(
                id=scenario.id,
                name=scenario.name,
                assumptions=json.loads(scenario.assumptions_json),
                tax_outcome=scenario.tax_outcome,
                savings_delta=scenario.savings_delta,
                risk_score=scenario.risk_score,
                required_evidence=json.loads(scenario.required_evidence_json),
                rank=scenario.rank,
            )
            for scenario in scenarios
        ]
    )


@router.post("/returns/{return_id}/attest", response_model=ReadinessResponse)
def attest_fact(
    return_id: str,
    payload: AttestRequest,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
    settings: Settings = Depends(get_settings),
) -> ReadinessResponse:
    try:
        create_attestation(session, return_id, payload.fact_id, actor.user_id, payload.rationale)
        refresh_system_issues(session, return_id)
    except ValueError as exc:
        raise HTTPException(status_code=_value_error_status(exc), detail=str(exc)) from exc

    readiness = evaluate_readiness(session, settings, return_id)
    return ReadinessResponse(**readiness.__dict__)


@router.post("/returns/{return_id}/approve", response_model=ApprovalResponse)
def approve_return(
    return_id: str,
    payload: ApprovalRequest,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ApprovalResponse:
    if actor.role not in {ApprovalRole.TAXPAYER, ApprovalRole.SPOUSE, ApprovalRole.CPA}:
        raise HTTPException(status_code=403, detail="Role not allowed for approval")

    event = ApprovalEvent(
        return_id=return_id,
        role=actor.role,
        actor_id=actor.user_id,
        decision=payload.decision,
        notes=payload.notes,
    )
    try:
        stored = record_approval(session, event)
        summary = approval_summary(session, return_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ApprovalResponse(
        event_id=stored.id,
        role=stored.role,
        decision=stored.decision,
        summary=ApprovalSummary(**summary),
    )


def _value_error_status(exc: ValueError) -> int:
    return 404 if "does not exist" in str(exc).lower() else 400


@router.get("/returns/{return_id}/export/freetaxusa", response_model=FreetaxusaExportResponse)
def export_return(
    return_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FreetaxusaExportResponse:
    payload = build_freetaxusa_export(session, settings, return_id)
    return FreetaxusaExportResponse(**payload)
