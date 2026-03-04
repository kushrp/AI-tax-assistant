from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
import re

from fastapi import UploadFile
from sqlmodel import Session, select

from tax_assistant.config import Settings
from tax_assistant.models import Document, DocumentQuality, SourceType, TaxReturn
from tax_assistant.services.storage_service import build_object_storage, build_storage_key


_DOC_TYPE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bw-?2c?\b", flags=re.IGNORECASE), "w2"),
    (re.compile(r"\b1099[-_\s]?int\b", flags=re.IGNORECASE), "1099-int"),
    (re.compile(r"\b1099[-_\s]?div\b", flags=re.IGNORECASE), "1099-div"),
    (re.compile(r"\b1099[-_\s]?b\b", flags=re.IGNORECASE), "1099-b"),
    (re.compile(r"\b1099[-_\s]?r\b", flags=re.IGNORECASE), "1099-r"),
    (re.compile(r"\b1099[-_\s]?nec\b", flags=re.IGNORECASE), "1099-nec"),
    (re.compile(r"\b1099[-_\s]?misc\b", flags=re.IGNORECASE), "1099-misc"),
    (re.compile(r"\b1099[-_\s]?k\b", flags=re.IGNORECASE), "1099-k"),
    (re.compile(r"\b1098[-_\s]?e\b", flags=re.IGNORECASE), "1098-e"),
    (re.compile(r"\b1098[-_\s]?t\b", flags=re.IGNORECASE), "1098-t"),
    (re.compile(r"\b1098\b", flags=re.IGNORECASE), "1098"),
    (re.compile(r"\b1095[-_\s]?[abc]?\b", flags=re.IGNORECASE), "1095"),
    (re.compile(r"\b(?:form[-_\s]?)?8606\b", flags=re.IGNORECASE), "8606"),
    (re.compile(r"\b5498\b", flags=re.IGNORECASE), "5498"),
    (re.compile(r"\b8949\b", flags=re.IGNORECASE), "8949"),
    (re.compile(r"\bschedule[-_\s]?d\b", flags=re.IGNORECASE), "schedule-d"),
    (re.compile(r"\bit[-_\s]?201\b", flags=re.IGNORECASE), "it-201"),
    (re.compile(r"\bnew[-_\s]?york\b|\bny[-_\s]?state\b", flags=re.IGNORECASE), "ny-state"),
    (
        re.compile(r"\b(crypto|coinbase|kraken|binance|gemini|etherscan|wallet)\b", flags=re.IGNORECASE),
        "crypto",
    ),
    (re.compile(r"\b(broker|brokerage|statement)\b", flags=re.IGNORECASE), "broker_statement"),
]

_CRYPTO_HEADER_SIGNATURES: list[set[str]] = [
    {"asset", "quantity", "price"},
    {"timestamp", "transaction_type", "amount"},
    {"date", "asset", "amount"},
]
_BROKER_HEADER_SIGNATURES: list[set[str]] = [
    {"proceeds", "cost_basis"},
    {"symbol", "proceeds", "cost_basis"},
]
_STRUCTURED_FACT_HEADERS = {"form_line_ref", "value"}


class DocumentUploadResult:
    def __init__(self, document: Document, duplicate: bool):
        self.document = document
        self.duplicate = duplicate


async def upload_document(
    session: Session,
    settings: Settings,
    *,
    return_id: str,
    tax_year: int,
    owner: str,
    source_type: SourceType,
    file: UploadFile,
) -> DocumentUploadResult:
    tax_return = session.get(TaxReturn, return_id)
    if not tax_return:
        raise ValueError(f"Return '{return_id}' does not exist")

    payload = await file.read()
    digest = hashlib.sha256(payload).hexdigest()

    existing = session.exec(select(Document).where(Document.sha256 == digest, Document.return_id == return_id)).first()
    if existing:
        return DocumentUploadResult(existing, duplicate=True)

    extension = Path(file.filename or "").suffix.lower()
    file_name = file.filename or f"upload-{digest[:8]}{extension or '.bin'}"
    storage = build_object_storage(settings)
    storage_key = build_storage_key(tax_year=tax_year, return_id=return_id, digest=digest, extension=extension or ".bin")
    stored = storage.store_bytes(storage_key, payload)

    quality = _resolve_quality(source_type, extension)
    doc_type = classify_doc_type(
        file_name,
        source_type=source_type,
        content_type=file.content_type or "",
        payload=payload,
    )

    document = Document(
        return_id=return_id,
        file_name=file_name,
        content_type=file.content_type or "application/octet-stream",
        source_type=source_type,
        quality_tier=quality,
        sha256=digest,
        storage_path=stored.location,
        classification_status="classified",
        doc_type=doc_type,
        tax_year=tax_year,
        owner=owner,
    )
    session.add(document)
    session.commit()
    session.refresh(document)

    return DocumentUploadResult(document, duplicate=False)


def read_document_payload(settings: Settings, document: Document) -> bytes:
    storage = build_object_storage(settings)
    return storage.read_bytes(document.storage_path)


def classify_doc_type(
    file_name: str,
    *,
    source_type: SourceType = SourceType.OTHER,
    content_type: str = "",
    payload: bytes | None = None,
) -> str:
    normalized_name = re.sub(r"[\s_]+", "-", file_name.lower())
    for rule, doc_type in _DOC_TYPE_RULES:
        if rule.search(normalized_name):
            return doc_type

    if source_type == SourceType.CSV or "csv" in content_type.lower() or normalized_name.endswith(".csv"):
        csv_type = _classify_csv_payload(payload or b"")
        return csv_type or "csv-generic"

    if source_type == SourceType.SCREENSHOT:
        return "screenshot"
    if source_type == SourceType.PHOTO:
        return "photo"

    return "unknown"


def _resolve_quality(source_type: SourceType, extension: str) -> DocumentQuality:
    if source_type in {SourceType.SCREENSHOT, SourceType.PHOTO}:
        return DocumentQuality.SUPPLEMENTAL
    if extension in {".png", ".jpg", ".jpeg", ".heic"}:
        return DocumentQuality.SUPPLEMENTAL
    return DocumentQuality.OFFICIAL


def _classify_csv_payload(payload: bytes) -> str | None:
    if not payload:
        return None

    sample = payload[:128_000].decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(sample))
    headers = {header.strip().lower() for header in (reader.fieldnames or []) if header}
    if not headers:
        return None

    if _STRUCTURED_FACT_HEADERS.issubset(headers):
        return "tax-facts-csv"
    if _header_signature_match(headers, _BROKER_HEADER_SIGNATURES):
        return "1099-b"
    if _header_signature_match(headers, _CRYPTO_HEADER_SIGNATURES):
        return "crypto"
    if {"payer", "interest"}.issubset(headers):
        return "1099-int"
    if {"payer", "ordinary_dividends"}.issubset(headers):
        return "1099-div"

    return None


def _header_signature_match(headers: set[str], signatures: list[set[str]]) -> bool:
    for signature in signatures:
        if signature.issubset(headers):
            return True
    return False
