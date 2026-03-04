from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader
from sqlmodel import Session

from tax_assistant.models import (
    Document,
    EvidenceLink,
    ExtractionJob,
    FactStatus,
    Materiality,
    SourceType,
    TaxFact,
    utcnow,
)


@dataclass
class ExtractedFact:
    form_line_ref: str
    value: float
    raw_value: str
    confidence: float
    source_locator: str
    extraction_method: str
    materiality: Materiality = Materiality.MATERIAL


_PDF_PATTERNS: list[tuple[str, str]] = [
    (r"wages[, ]+tips[, ]+other compensation\s*\$?\s*([\d,]+(?:\.\d{2})?)", "1040.line1a.wages"),
    (r"federal income tax withheld\s*\$?\s*([\d,]+(?:\.\d{2})?)", "1040.line25a.withholding"),
    (r"taxable interest\s*\$?\s*([\d,]+(?:\.\d{2})?)", "1040.line2b.taxable_interest"),
    (r"ordinary dividends\s*\$?\s*([\d,]+(?:\.\d{2})?)", "1040.line3b.ordinary_dividends"),
    (r"qualified dividends\s*\$?\s*([\d,]+(?:\.\d{2})?)", "1040.line3a.qualified_dividends"),
    (r"proceeds\s*\$?\s*([\d,]+(?:\.\d{2})?)", "schedule_d.total_proceeds"),
    (r"cost basis\s*\$?\s*([\d,]+(?:\.\d{2})?)", "schedule_d.total_basis"),
    (r"ira distributions\s*\$?\s*([\d,]+(?:\.\d{2})?)", "1040.line4a.ira_distributions"),
    (r"taxable amount\s*\$?\s*([\d,]+(?:\.\d{2})?)", "1040.line4b.taxable_ira"),
    (r"mortgage interest received from payer\s*\$?\s*([\d,]+(?:\.\d{2})?)", "schedule_a.mortgage_interest"),
]

_CSV_COLUMN_MAP = {
    "wages": "1040.line1a.wages",
    "taxable_interest": "1040.line2b.taxable_interest",
    "ordinary_dividends": "1040.line3b.ordinary_dividends",
    "qualified_dividends": "1040.line3a.qualified_dividends",
    "ira_distributions": "1040.line4a.ira_distributions",
    "taxable_ira": "1040.line4b.taxable_ira",
    "withholding": "1040.line25a.withholding",
    "mortgage_interest": "schedule_a.mortgage_interest",
    "property_tax": "schedule_a.property_tax",
    "charity": "schedule_a.charity",
    "student_loan_interest": "schedule_1.student_loan_interest",
    "capital_loss_carryover": "schedule_d.capital_loss_carryover",
    "proceeds": "schedule_d.total_proceeds",
    "cost_basis": "schedule_d.total_basis",
    "conversion_amount": "roth.conversion.amount",
}


def run_extraction(session: Session, document: Document) -> tuple[ExtractionJob, list[TaxFact]]:
    job = ExtractionJob(document_id=document.id, status="pending", extractor="hybrid")
    session.add(job)
    session.commit()
    session.refresh(job)

    job.status = "running"
    job.started_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)

    try:
        extracted = extract_facts(document)
        facts: list[TaxFact] = []
        for item in extracted:
            fact = TaxFact(
                return_id=document.return_id,
                tax_year=document.tax_year,
                form_line_ref=item.form_line_ref,
                value=item.value,
                raw_value=item.raw_value,
                source_doc_id=document.id,
                source_locator=item.source_locator,
                confidence=item.confidence,
                materiality=item.materiality,
                status=FactStatus.EXTRACTED,
            )
            session.add(fact)
            session.flush()

            evidence = EvidenceLink(
                fact_id=fact.id,
                doc_id=document.id,
                page=_parse_page(item.source_locator),
                bbox=_locator_to_bbox(item.source_locator),
                extraction_method=item.extraction_method,
                checksum=document.sha256,
            )
            session.add(evidence)
            facts.append(fact)

        job.status = "completed"
        job.completed_at = utcnow()
        session.add(job)
        session.commit()
        for fact in facts:
            session.refresh(fact)
        session.refresh(job)
        return job, facts
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.completed_at = utcnow()
        session.add(job)
        session.commit()
        raise


def extract_facts(document: Document) -> list[ExtractedFact]:
    path = Path(document.storage_path)
    source = document.source_type

    if source == SourceType.CSV or path.suffix.lower() == ".csv":
        return _extract_from_csv(path)

    if path.suffix.lower() == ".pdf":
        return _extract_from_pdf(path)

    if source in {SourceType.SCREENSHOT, SourceType.PHOTO} or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".heic"}:
        return _extract_from_image(path, fallback_name=document.file_name)

    return []


def _extract_from_csv(path: Path) -> list[ExtractedFact]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    facts: list[ExtractedFact] = []

    if not rows:
        return facts

    headers = {h.lower() for h in rows[0].keys() if h}

    if {"form_line_ref", "value"}.issubset(headers):
        for idx, row in enumerate(rows, start=1):
            ref = (row.get("form_line_ref") or row.get("FORM_LINE_REF") or "").strip()
            raw = (row.get("value") or row.get("VALUE") or "").strip()
            value = _parse_money(raw)
            if not ref:
                continue
            facts.append(
                ExtractedFact(
                    form_line_ref=ref,
                    value=value,
                    raw_value=raw,
                    confidence=0.99,
                    source_locator=f"row:{idx}",
                    extraction_method="csv-direct",
                    materiality=_materiality_for_ref(ref),
                )
            )
        return facts

    for idx, row in enumerate(rows, start=1):
        lowered = {k.lower(): (v or "") for k, v in row.items() if k}

        if "type" in lowered and "amount" in lowered and (lowered.get("type") or "").lower() in _CSV_COLUMN_MAP:
            ref = _CSV_COLUMN_MAP[lowered["type"].lower()]
            raw = lowered.get("amount", "")
            facts.append(
                ExtractedFact(
                    form_line_ref=ref,
                    value=_parse_money(raw),
                    raw_value=raw,
                    confidence=0.97,
                    source_locator=f"row:{idx}",
                    extraction_method="csv-type-amount",
                    materiality=_materiality_for_ref(ref),
                )
            )
            continue

        for key, ref in _CSV_COLUMN_MAP.items():
            if key in lowered and lowered[key] != "":
                raw = lowered[key]
                facts.append(
                    ExtractedFact(
                        form_line_ref=ref,
                        value=_parse_money(raw),
                        raw_value=raw,
                        confidence=0.97,
                        source_locator=f"row:{idx}",
                        extraction_method="csv-column-map",
                        materiality=_materiality_for_ref(ref),
                    )
                )

        if {"proceeds", "cost_basis"}.issubset(lowered.keys()):
            proceeds_raw = lowered["proceeds"]
            basis_raw = lowered["cost_basis"]
            facts.append(
                ExtractedFact(
                    form_line_ref="schedule_d.total_proceeds",
                    value=_parse_money(proceeds_raw),
                    raw_value=proceeds_raw,
                    confidence=0.98,
                    source_locator=f"row:{idx}",
                    extraction_method="csv-broker-row",
                )
            )
            facts.append(
                ExtractedFact(
                    form_line_ref="schedule_d.total_basis",
                    value=_parse_money(basis_raw),
                    raw_value=basis_raw,
                    confidence=0.98,
                    source_locator=f"row:{idx}",
                    extraction_method="csv-broker-row",
                )
            )

    return _merge_duplicate_facts(facts)


def _extract_from_pdf(path: Path) -> list[ExtractedFact]:
    reader = PdfReader(str(path))
    facts: list[ExtractedFact] = []

    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        normalized = re.sub(r"\s+", " ", text.lower())
        for pattern, ref in _PDF_PATTERNS:
            for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
                raw = match.group(1)
                facts.append(
                    ExtractedFact(
                        form_line_ref=ref,
                        value=_parse_money(raw),
                        raw_value=raw,
                        confidence=0.9,
                        source_locator=f"page:{index}",
                        extraction_method="pdf-regex",
                        materiality=_materiality_for_ref(ref),
                    )
                )

        if "backdoor roth" in normalized or "conversion" in normalized:
            for match in re.finditer(r"conversion\s*\$?\s*([\d,]+(?:\.\d{2})?)", normalized):
                raw = match.group(1)
                facts.append(
                    ExtractedFact(
                        form_line_ref="roth.conversion.amount",
                        value=_parse_money(raw),
                        raw_value=raw,
                        confidence=0.85,
                        source_locator=f"page:{index}",
                        extraction_method="pdf-regex",
                    )
                )

    return _merge_duplicate_facts(facts)


def _extract_from_image(path: Path, fallback_name: str = "") -> list[ExtractedFact]:
    text, ocr_available = _read_image_text(path)

    normalized = re.sub(r"\s+", " ", text.lower())
    facts: list[ExtractedFact] = []
    extraction_method = "ocr" if ocr_available else "ocr-unavailable"
    default_confidence = 0.62 if ocr_available else 0.18

    for pattern, ref in _PDF_PATTERNS:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1)
        facts.append(
            ExtractedFact(
                form_line_ref=ref,
                value=_parse_money(raw),
                raw_value=raw,
                confidence=default_confidence,
                source_locator="image:ocr" if ocr_available else "image:ocr-unavailable",
                extraction_method=extraction_method,
                materiality=_materiality_for_ref(ref),
            )
        )

    if not facts and fallback_name:
        stem = Path(fallback_name).stem.lower()
        inferred = "unmapped.image_amount"
        for hint, ref in (
            ("wage", "1040.line1a.wages"),
            ("interest", "1040.line2b.taxable_interest"),
            ("dividend", "1040.line3b.ordinary_dividends"),
            ("withhold", "1040.line25a.withholding"),
            ("ira", "1040.line4a.ira_distributions"),
            ("conversion", "roth.conversion.amount"),
        ):
            if hint in stem:
                inferred = ref
                break

        if inferred != "unmapped.image_amount":
            numbers = re.findall(r"([\d,]+(?:\.\d{2})?)", stem)
            if numbers:
                raw = numbers[0]
                facts.append(
                    ExtractedFact(
                        form_line_ref=inferred,
                        value=_parse_money(raw),
                        raw_value=raw,
                        confidence=0.42 if ocr_available else 0.15,
                        source_locator="image:file-name" if ocr_available else "image:ocr-unavailable",
                        extraction_method="ocr-fallback" if ocr_available else "ocr-unavailable",
                        materiality=_materiality_for_ref(inferred),
                    )
                )

    if not facts and not ocr_available:
        facts.append(
            ExtractedFact(
                form_line_ref="unmapped.ocr_unavailable",
                value=0.0,
                raw_value="",
                confidence=0.1,
                source_locator="image:ocr-unavailable",
                extraction_method="ocr-unavailable",
                materiality=Materiality.NON_MATERIAL,
            )
        )

    return _merge_duplicate_facts(facts)


def _materiality_for_ref(ref: str) -> Materiality:
    non_material_prefixes = ("notes.", "unmapped.")
    if ref.startswith(non_material_prefixes):
        return Materiality.NON_MATERIAL
    return Materiality.MATERIAL


def _parse_money(value: str) -> float:
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0.0
    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    if is_negative:
        cleaned = cleaned[1:-1].strip()

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return 0.0

    amount = float(match.group(0))
    if is_negative and amount > 0:
        amount = -amount
    return amount


def _parse_page(locator: str) -> int | None:
    if not locator.startswith("page:"):
        return None
    try:
        return int(locator.split(":", maxsplit=1)[1])
    except ValueError:
        return None


def _merge_duplicate_facts(facts: Iterable[ExtractedFact]) -> list[ExtractedFact]:
    merged: dict[tuple[str, str], ExtractedFact] = {}
    for fact in facts:
        key = (fact.form_line_ref, fact.source_locator)
        prior = merged.get(key)
        if not prior or prior.confidence < fact.confidence:
            merged[key] = fact
    return list(merged.values())


def _read_image_text(path: Path) -> tuple[str, bool]:
    try:
        import pytesseract  # type: ignore
        from PIL import Image

        return pytesseract.image_to_string(Image.open(path)), True
    except FileNotFoundError:
        raise
    except Exception:
        return "", False


def _locator_to_bbox(locator: str) -> str | None:
    if not locator or locator.startswith("page:"):
        return None
    return locator
