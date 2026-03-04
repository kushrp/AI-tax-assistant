from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from tax_assistant.models import ApprovalDecision, ApprovalRole, FilingStatus, Materiality


class CreateReturnRequest(BaseModel):
    tax_year: int = Field(default=2025, ge=2000, le=2100)
    primary_state: str = Field(default="NY", min_length=2, max_length=2)
    filing_status: FilingStatus = FilingStatus.MFJ

    @field_validator("primary_state")
    @classmethod
    def normalize_primary_state(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("primary_state must be a two-letter state code")
        return normalized


class HealthResponse(BaseModel):
    status: str
    database: str


class ClientConfigResponse(BaseModel):
    api_base_url: str


class ReturnResponse(BaseModel):
    id: str
    tax_year: int
    primary_state: str
    filing_status: str
    status: str
    created_at: datetime


class UploadResponse(BaseModel):
    document_id: str
    classification_status: str
    doc_type: str
    duplicate: bool = False


class ExtractionResponse(BaseModel):
    extraction_job_id: str
    document_id: str
    extracted_facts: int
    issues_created: int


class ReturnDocumentResponse(BaseModel):
    id: str
    return_id: str
    file_name: str
    source_type: str
    doc_type: str
    tax_year: int
    owner: str
    created_at: datetime
    latest_extraction_job_id: Optional[str] = None
    latest_extraction_status: Optional[str] = None
    facts_extracted: int = 0


class ExtractAllRequest(BaseModel):
    force: bool = False


class ExtractAllDocumentResult(BaseModel):
    document_id: str
    status: str
    extracted_facts: int
    extraction_job_id: Optional[str] = None
    error: Optional[str] = None


class ExtractAllResponse(BaseModel):
    return_id: str
    processed: int
    succeeded: int
    skipped: int
    failed: int
    open_issues: int
    documents: list[ExtractAllDocumentResult]


class TaxFactResponse(BaseModel):
    id: str
    return_id: str
    tax_year: int
    form_line_ref: str
    value: float
    raw_value: str
    source_doc_id: str
    source_locator: str
    confidence: float
    materiality: Materiality
    status: str


class EvidenceProvenanceResponse(BaseModel):
    page: Optional[int] = None
    bbox: Optional[str] = None
    extraction_method: str
    checksum: str
    source_locator: Optional[str] = None


class EvidenceLinkResponse(BaseModel):
    id: str
    fact_id: str
    doc_id: str
    provenance: EvidenceProvenanceResponse
    created_at: datetime


class IssueResponse(BaseModel):
    id: str
    severity: str
    category: str
    title: str
    description: str
    blocking: bool
    recommended_action: str
    owner: Optional[str]
    status: str


class IssueTransitionRequest(BaseModel):
    note: Optional[str] = None


class IssueTransitionResponse(BaseModel):
    id: str
    status: str
    category: str
    title: str
    blocking: bool
    acted_by: str
    note: Optional[str] = None


class OptimizeRequest(BaseModel):
    include_itemized: bool = True


class OptimizationScenarioResponse(BaseModel):
    id: str
    name: str
    assumptions: dict[str, Any]
    tax_outcome: float
    savings_delta: float
    risk_score: float
    required_evidence: list[str]
    rank: int


class OptimizeResponse(BaseModel):
    scenarios: list[OptimizationScenarioResponse]


class AttestRequest(BaseModel):
    fact_id: str
    rationale: str = Field(min_length=5)


class ApprovalRequest(BaseModel):
    decision: ApprovalDecision
    notes: Optional[str] = None


class ApprovalSummary(BaseModel):
    taxpayer: Optional[str]
    spouse: Optional[str]
    cpa: Optional[str]


class ApprovalResponse(BaseModel):
    event_id: str
    role: ApprovalRole
    decision: ApprovalDecision
    summary: ApprovalSummary


class ApprovalEventResponse(BaseModel):
    id: str
    return_id: str
    role: ApprovalRole
    actor_id: str
    decision: ApprovalDecision
    notes: Optional[str] = None
    created_at: datetime


class ReadinessResponse(BaseModel):
    ready_to_file: bool
    material_fields_total: int
    evidenced_or_attested: int
    evidence_coverage_pct: float
    open_blocking_issues: int
    blockers: list[str]


class ExportField(BaseModel):
    field_key: str
    value: float
    fact_id: str
    source_doc_id: str
    confidence: float


class FreetaxusaExportResponse(BaseModel):
    return_id: str
    tax_year: int
    generated_at: datetime
    ready_to_file: bool
    fields: list[ExportField]
    unresolved_question_queue: list[str]
    evidence_report: dict[str, Any]
    audit_summary: dict[str, Any]


class MappingOverrideRequest(BaseModel):
    canonical_fact_ref: str = Field(min_length=3)
    status: str = Field(pattern="^(verified|unverified)$")
    reason: Optional[str] = None


class MappingEntryResponse(BaseModel):
    pack_version: str
    canonical_fact_ref: str
    export_field_key: str
    status: str
    verification_note: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class MappingOverrideResponse(BaseModel):
    canonical_fact_ref: str
    status: str
    reason: Optional[str] = None
    updated_by: str
    updated_at: datetime


class RetentionRunResponse(BaseModel):
    executed_at: datetime
    result: dict[str, int]


class ActorContext(BaseModel):
    user_id: str = "anonymous"
    role: ApprovalRole = ApprovalRole.TAXPAYER
