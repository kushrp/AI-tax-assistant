from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from tax_assistant.config import Settings
from tax_assistant.deps import get_authenticated_actor, get_cpa_actor, get_session, get_settings
from tax_assistant.models import (
    ApprovalEvent,
    ApprovalRole,
    Document,
    ExtractionJob,
    Issue,
    MappingStatus,
    IssueStatus,
    SourceType,
    TaxFact,
    TaxReturn,
)
from tax_assistant.schemas import (
    ActorContext,
    ClientConfigResponse,
    ExtractAllRequest,
    ExtractAllResponse,
    ExtractAllDocumentResult,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalSummary,
    AttestRequest,
    CreateReturnRequest,
    ExtractionResponse,
    FreetaxusaExportResponse,
    IssueTransitionRequest,
    IssueTransitionResponse,
    IssueResponse,
    MappingEntryResponse,
    MappingOverrideRequest,
    MappingOverrideResponse,
    OptimizeRequest,
    OptimizeResponse,
    OptimizationScenarioResponse,
    ReadinessResponse,
    RetentionRunResponse,
    ReturnDocumentResponse,
    ReturnResponse,
    TaxFactResponse,
    UploadResponse,
)
from tax_assistant.services.confidence_service import evaluate_readiness
from tax_assistant.services.document_service import upload_document
from tax_assistant.services.export_service import build_freetaxusa_export
from tax_assistant.services.freetaxusa_mapping import effective_mapping_rows, set_mapping_override
from tax_assistant.services.extraction_service import run_extraction
from tax_assistant.services.optimization_service import approval_summary, create_attestation, generate_scenarios, record_approval
from tax_assistant.services.retention_service import apply_retention_policy
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


@router.get("/client-config", response_model=ClientConfigResponse)
def client_config(settings: Settings = Depends(get_settings)) -> ClientConfigResponse:
    return ClientConfigResponse(api_base_url=settings.normalized_api_base_url)


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
def extract_document_route(
    document_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ExtractionResponse:
    document = session.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        job, facts = run_extraction(session, settings, document)
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


@router.get("/returns/{return_id}/documents", response_model=list[ReturnDocumentResponse])
def list_documents(return_id: str, session: Session = Depends(get_session)) -> list[ReturnDocumentResponse]:
    tax_return = session.get(TaxReturn, return_id)
    if not tax_return:
        raise HTTPException(status_code=404, detail=f"Return '{return_id}' does not exist")

    documents = list(
        session.exec(
            select(Document)
            .where(Document.return_id == return_id)
            .order_by(Document.created_at, Document.id)
        )
    )
    if not documents:
        return []

    doc_ids = [doc.id for doc in documents]
    facts = list(session.exec(select(TaxFact).where(TaxFact.source_doc_id.in_(doc_ids))))
    facts_by_doc: dict[str, int] = {}
    for fact in facts:
        facts_by_doc[fact.source_doc_id] = facts_by_doc.get(fact.source_doc_id, 0) + 1

    jobs = list(session.exec(select(ExtractionJob).where(ExtractionJob.document_id.in_(doc_ids))))
    latest_job_by_doc: dict[str, ExtractionJob] = {}
    for job in jobs:
        prior = latest_job_by_doc.get(job.document_id)
        if not prior or (job.started_at, job.id) > (prior.started_at, prior.id):
            latest_job_by_doc[job.document_id] = job

    response: list[ReturnDocumentResponse] = []
    for doc in documents:
        latest_job = latest_job_by_doc.get(doc.id)
        response.append(
            ReturnDocumentResponse(
                id=doc.id,
                return_id=doc.return_id,
                file_name=doc.file_name,
                source_type=doc.source_type.value,
                doc_type=doc.doc_type,
                tax_year=doc.tax_year,
                owner=doc.owner,
                created_at=doc.created_at,
                latest_extraction_job_id=latest_job.id if latest_job else None,
                latest_extraction_status=latest_job.status if latest_job else None,
                facts_extracted=facts_by_doc.get(doc.id, 0),
            )
        )
    return response


@router.post("/returns/{return_id}/extract-all", response_model=ExtractAllResponse)
def extract_all_documents(
    return_id: str,
    payload: ExtractAllRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ExtractAllResponse:
    tax_return = session.get(TaxReturn, return_id)
    if not tax_return:
        raise HTTPException(status_code=404, detail=f"Return '{return_id}' does not exist")

    documents = list(session.exec(select(Document).where(Document.return_id == return_id).order_by(Document.created_at)))
    doc_ids = [doc.id for doc in documents]
    existing_jobs = (
        list(session.exec(select(ExtractionJob).where(ExtractionJob.document_id.in_(doc_ids))))
        if doc_ids
        else []
    )
    latest_job_by_doc: dict[str, ExtractionJob] = {}
    for job in existing_jobs:
        prior = latest_job_by_doc.get(job.document_id)
        if not prior or (job.started_at, job.id) > (prior.started_at, prior.id):
            latest_job_by_doc[job.document_id] = job

    results: list[ExtractAllDocumentResult] = []
    succeeded = 0
    skipped = 0
    failed = 0

    for document in documents:
        latest_job = latest_job_by_doc.get(document.id)
        if not payload.force and latest_job and latest_job.status == "completed":
            skipped += 1
            facts_count = len(
                list(session.exec(select(TaxFact.id).where(TaxFact.source_doc_id == document.id)))
            )
            results.append(
                ExtractAllDocumentResult(
                    document_id=document.id,
                    status="skipped",
                    extraction_job_id=latest_job.id,
                    extracted_facts=facts_count,
                )
            )
            continue

        try:
            job, facts = run_extraction(session, settings, document)
            succeeded += 1
            results.append(
                ExtractAllDocumentResult(
                    document_id=document.id,
                    status=job.status,
                    extraction_job_id=job.id,
                    extracted_facts=len(facts),
                )
            )
        except FileNotFoundError as exc:
            failed += 1
            results.append(
                ExtractAllDocumentResult(
                    document_id=document.id,
                    status="failed",
                    extracted_facts=0,
                    error=f"Document file missing: {exc}",
                )
            )
        except Exception as exc:
            failed += 1
            results.append(
                ExtractAllDocumentResult(
                    document_id=document.id,
                    status="failed",
                    extracted_facts=0,
                    error=f"Extraction failed: {exc}",
                )
            )

    issues = refresh_system_issues(session, return_id)
    return ExtractAllResponse(
        return_id=return_id,
        processed=len(documents),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        open_issues=len(issues),
        documents=results,
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


@router.post("/issues/{issue_id}/resolve", response_model=IssueTransitionResponse)
def resolve_issue(
    issue_id: str,
    payload: IssueTransitionRequest,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_cpa_actor),
) -> IssueTransitionResponse:
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.RESOLVED
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return IssueTransitionResponse(
        id=issue.id,
        status=issue.status.value,
        category=issue.category,
        title=issue.title,
        blocking=issue.blocking,
        acted_by=actor.user_id,
        note=payload.note,
    )


@router.post("/issues/{issue_id}/reopen", response_model=IssueTransitionResponse)
def reopen_issue(
    issue_id: str,
    payload: IssueTransitionRequest,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_cpa_actor),
) -> IssueTransitionResponse:
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.OPEN
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return IssueTransitionResponse(
        id=issue.id,
        status=issue.status.value,
        category=issue.category,
        title=issue.title,
        blocking=issue.blocking,
        acted_by=actor.user_id,
        note=payload.note,
    )


@router.get("/mappings/freetaxusa", response_model=list[MappingEntryResponse])
def list_freetaxusa_mappings(session: Session = Depends(get_session)) -> list[MappingEntryResponse]:
    rows = effective_mapping_rows(session)
    return [MappingEntryResponse(**row) for row in rows]


@router.post("/mappings/freetaxusa/overrides", response_model=MappingOverrideResponse)
def create_mapping_override(
    payload: MappingOverrideRequest,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_cpa_actor),
) -> MappingOverrideResponse:
    try:
        status = MappingStatus(payload.status)
        override = set_mapping_override(
            session,
            canonical_fact_ref=payload.canonical_fact_ref,
            status=status,
            actor_id=actor.user_id,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MappingOverrideResponse(
        canonical_fact_ref=override.canonical_fact_ref,
        status=override.status.value,
        reason=override.reason,
        updated_by=override.updated_by,
        updated_at=override.updated_at,
    )


@router.post("/admin/retention/run", response_model=RetentionRunResponse)
def run_retention(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: ActorContext = Depends(get_cpa_actor),
) -> RetentionRunResponse:
    result = apply_retention_policy(session, settings)
    return RetentionRunResponse(executed_at=datetime.now(timezone.utc), result=result.to_dict())


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
    actor: ActorContext = Depends(get_authenticated_actor),
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
    actor: ActorContext = Depends(get_authenticated_actor),
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
