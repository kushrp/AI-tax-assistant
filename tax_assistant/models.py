from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, Float, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class ReturnStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    READY_TO_FILE = "ready_to_file"
    FILED = "filed"


class FilingStatus(str, Enum):
    SINGLE = "single"
    MFJ = "mfj"
    MFS = "mfs"
    HOH = "hoh"


class SourceType(str, Enum):
    PDF = "pdf"
    CSV = "csv"
    SCREENSHOT = "screenshot"
    PHOTO = "photo"
    OTHER = "other"


class DocumentQuality(str, Enum):
    OFFICIAL = "official"
    SUPPLEMENTAL = "supplemental"


class Materiality(str, Enum):
    MATERIAL = "material"
    NON_MATERIAL = "non_material"


class FactStatus(str, Enum):
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    ATTESTED = "attested"
    REJECTED = "rejected"


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class MappingStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class ApprovalRole(str, Enum):
    TAXPAYER = "taxpayer"
    SPOUSE = "spouse"
    CPA = "cpa"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class TaxReturn(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    tax_year: int = Field(index=True, default=2025)
    primary_state: str = Field(default="NY")
    filing_status: FilingStatus = Field(default=FilingStatus.MFJ)
    status: ReturnStatus = Field(default=ReturnStatus.IN_PROGRESS)
    created_by: str = Field(default="system")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    return_id: str = Field(index=True, foreign_key="taxreturn.id")
    file_name: str
    content_type: str = Field(default="application/octet-stream")
    source_type: SourceType = Field(default=SourceType.OTHER)
    quality_tier: DocumentQuality = Field(default=DocumentQuality.OFFICIAL)
    sha256: str = Field(index=True)
    storage_path: str
    classification_status: str = Field(default="classified")
    doc_type: str = Field(default="unknown", index=True)
    tax_year: int = Field(index=True)
    owner: str = Field(default="taxpayer")
    created_at: datetime = Field(default_factory=utcnow)


class ExtractionJob(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    document_id: str = Field(index=True, foreign_key="document.id")
    status: str = Field(default="pending")
    extractor: str = Field(default="hybrid")
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None


class TaxFact(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    return_id: str = Field(index=True, foreign_key="taxreturn.id")
    tax_year: int = Field(index=True)
    form_line_ref: str = Field(index=True)
    value: float = Field(sa_column=Column(Float))
    currency: str = Field(default="USD")
    raw_value: str = Field(default="")
    source_doc_id: str = Field(index=True, foreign_key="document.id")
    source_locator: str = Field(default="")
    confidence: float = Field(default=0.0)
    materiality: Materiality = Field(default=Materiality.MATERIAL)
    status: FactStatus = Field(default=FactStatus.EXTRACTED)
    created_at: datetime = Field(default_factory=utcnow)


class EvidenceLink(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    fact_id: str = Field(index=True, foreign_key="taxfact.id")
    doc_id: str = Field(index=True, foreign_key="document.id")
    page: Optional[int] = None
    bbox: Optional[str] = None
    extraction_method: str = Field(default="unknown", index=True)
    checksum: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Issue(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    return_id: str = Field(index=True, foreign_key="taxreturn.id")
    severity: IssueSeverity = Field(default=IssueSeverity.MEDIUM, index=True)
    category: str = Field(index=True)
    title: str
    description: str
    blocking: bool = Field(default=False, index=True)
    recommended_action: str = Field(default="")
    owner: Optional[str] = Field(default=None)
    status: IssueStatus = Field(default=IssueStatus.OPEN)
    created_at: datetime = Field(default_factory=utcnow)


class OptimizationScenario(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    return_id: str = Field(index=True, foreign_key="taxreturn.id")
    name: str
    assumptions_json: str = Field(sa_column=Column(Text), default="{}")
    tax_outcome: float = Field(default=0.0)
    savings_delta: float = Field(default=0.0)
    risk_score: float = Field(default=0.0)
    required_evidence_json: str = Field(sa_column=Column(Text), default="[]")
    rank: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)


class Attestation(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    return_id: str = Field(index=True, foreign_key="taxreturn.id")
    fact_id: str = Field(index=True, foreign_key="taxfact.id")
    actor_id: str = Field(index=True)
    rationale: str
    created_at: datetime = Field(default_factory=utcnow)


class ApprovalEvent(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    return_id: str = Field(index=True, foreign_key="taxreturn.id")
    role: ApprovalRole = Field(index=True)
    actor_id: str = Field(index=True)
    decision: ApprovalDecision = Field(index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class MappingOverride(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    pack_version: str = Field(index=True, default="freetaxusa_2025")
    canonical_fact_ref: str = Field(index=True)
    status: MappingStatus = Field(default=MappingStatus.UNVERIFIED, index=True)
    reason: Optional[str] = None
    updated_by: str = Field(index=True, default="system")
    updated_at: datetime = Field(default_factory=utcnow)
