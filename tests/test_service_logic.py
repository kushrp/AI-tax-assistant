from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import select

from tax_assistant.config import Settings
from tax_assistant.models import (
    ApprovalDecision,
    ApprovalEvent,
    ApprovalRole,
    Attestation,
    Document,
    DocumentQuality,
    EvidenceLink,
    FactStatus,
    FilingStatus,
    Issue,
    IssueStatus,
    MappingStatus,
    Materiality,
    SourceType,
    TaxFact,
    TaxReturn,
)
from tax_assistant.services.confidence_service import evaluate_readiness
from tax_assistant.services.document_service import classify_doc_type
from tax_assistant.services.extraction_service import extract_facts
from tax_assistant.services.export_service import build_freetaxusa_export
from tax_assistant.services.freetaxusa_mapping import effective_mapping_status, set_mapping_override
from tax_assistant.services.optimization_service import generate_scenarios
from tax_assistant.services.retention_service import apply_retention_policy
from tax_assistant.services.rules_engine import refresh_system_issues
from tax_assistant.services.storage_service import build_object_storage, build_storage_key


def _create_return(session, *, tax_year: int = 2025, filing_status: FilingStatus = FilingStatus.MFJ) -> TaxReturn:
    tax_return = TaxReturn(tax_year=tax_year, primary_state="NY", filing_status=filing_status)
    session.add(tax_return)
    session.commit()
    session.refresh(tax_return)
    return tax_return


def _create_document(
    session,
    *,
    return_id: str,
    file_name: str,
    doc_type: str = "unknown",
    tax_year: int = 2025,
    source_type: SourceType = SourceType.CSV,
    quality_tier: DocumentQuality = DocumentQuality.OFFICIAL,
) -> Document:
    document = Document(
        return_id=return_id,
        file_name=file_name,
        content_type="text/csv",
        source_type=source_type,
        quality_tier=quality_tier,
        sha256=f"sha-{file_name}-{tax_year}",
        storage_path=f"/tmp/{file_name}",
        classification_status="classified",
        doc_type=doc_type,
        tax_year=tax_year,
        owner="taxpayer",
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def test_classify_doc_type_detects_8606_variants_and_csv_signatures():
    assert classify_doc_type("form8606_prior.pdf") == "8606"

    structured_csv = b"form_line_ref,value\n1040.line1a.wages,100000\n"
    assert (
        classify_doc_type(
            "facts.csv",
            source_type=SourceType.CSV,
            content_type="text/csv",
            payload=structured_csv,
        )
        == "tax-facts-csv"
    )

    broker_csv = b"symbol,proceeds,cost_basis\nAAPL,100,90\n"
    assert (
        classify_doc_type(
            "transactions.csv",
            source_type=SourceType.CSV,
            content_type="text/csv",
            payload=broker_csv,
        )
        == "1099-b"
    )


def test_extract_facts_supports_new_york_csv_columns(tmp_path: Path):
    csv_path = tmp_path / "ny_state.csv"
    csv_path.write_text(
        "ny_wages,ny_agi,ny_taxable_income,ny_state_tax,ny_withholding\n"
        "120000,118500,103000,6100,6500\n",
        encoding="utf-8",
    )
    document = Document(
        return_id="return-ny",
        file_name="ny_state.csv",
        content_type="text/csv",
        source_type=SourceType.CSV,
        quality_tier=DocumentQuality.OFFICIAL,
        sha256="sha-ny",
        storage_path=str(csv_path),
        classification_status="classified",
        doc_type="it-201",
        tax_year=2025,
        owner="taxpayer",
    )

    facts = extract_facts(document)
    refs = {fact.form_line_ref for fact in facts}
    assert "ny.it201.line1.wages" in refs
    assert "ny.it201.line33.new_york_adjusted_gross_income" in refs
    assert "ny.it201.line37.new_york_taxable_income" in refs
    assert "ny.it201.line46.new_york_state_tax" in refs
    assert "ny.it201.line61.new_york_state_withholding" in refs


def test_extract_facts_image_fallback_uses_original_upload_name(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "2dc4f31a79.png"
    image_path.write_bytes(b"fake-image")

    document = Document(
        return_id="return-1",
        file_name="wages_12345.png",
        content_type="image/png",
        source_type=SourceType.SCREENSHOT,
        quality_tier=DocumentQuality.SUPPLEMENTAL,
        sha256="abc123",
        storage_path=str(image_path),
        classification_status="classified",
        doc_type="screenshot",
        tax_year=2025,
        owner="taxpayer",
    )

    monkeypatch.setattr(
        "tax_assistant.services.extraction_service._read_image_text",
        lambda _path: ("", False),
    )

    facts = extract_facts(document)
    assert len(facts) == 1
    assert facts[0].form_line_ref == "1040.line1a.wages"
    assert facts[0].value == 12345.0
    assert facts[0].confidence == 0.15


def test_refresh_system_issues_is_idempotent_and_flags_missing_coverage(session):
    tax_return = _create_return(session)
    document = _create_document(session, return_id=tax_return.id, file_name="w2.csv")

    fact = TaxFact(
        return_id=tax_return.id,
        tax_year=tax_return.tax_year,
        form_line_ref="1040.line1a.wages",
        value=95000.0,
        raw_value="95000",
        source_doc_id=document.id,
        source_locator="row:1",
        confidence=0.95,
        materiality=Materiality.MATERIAL,
        status=FactStatus.EXTRACTED,
    )
    session.add(fact)
    session.commit()

    refresh_system_issues(session, tax_return.id)
    refresh_system_issues(session, tax_return.id)

    open_issues = list(
        session.exec(
            select(Issue).where(
                Issue.return_id == tax_return.id,
                Issue.status == IssueStatus.OPEN,
            )
        )
    )
    categories = [issue.category for issue in open_issues]
    assert categories.count("system.evidence.missing_coverage") == 1


def test_refresh_system_issues_flags_unmapped_material_fields(session):
    tax_return = _create_return(session)
    document = _create_document(session, return_id=tax_return.id, file_name="custom.csv")

    fact = TaxFact(
        return_id=tax_return.id,
        tax_year=tax_return.tax_year,
        form_line_ref="custom.income_adjustment",
        value=2500.0,
        raw_value="2500",
        source_doc_id=document.id,
        source_locator="row:1",
        confidence=0.97,
        materiality=Materiality.MATERIAL,
        status=FactStatus.EXTRACTED,
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)

    session.add(
        EvidenceLink(
            fact_id=fact.id,
            doc_id=document.id,
            extraction_method="csv-direct",
            checksum=document.sha256,
        )
    )
    session.commit()

    refresh_system_issues(session, tax_return.id)

    open_issues = list(
        session.exec(
            select(Issue).where(
                Issue.return_id == tax_return.id,
                Issue.status == IssueStatus.OPEN,
            )
        )
    )
    categories = {issue.category for issue in open_issues}
    assert "system.export.unmapped_material_fields" in categories


def test_evaluate_readiness_counts_evidence_and_attestation(session, test_settings):
    tax_return = _create_return(session)
    doc_one = _create_document(session, return_id=tax_return.id, file_name="w2.csv")
    doc_two = _create_document(session, return_id=tax_return.id, file_name="1099.csv")

    fact_one = TaxFact(
        return_id=tax_return.id,
        tax_year=tax_return.tax_year,
        form_line_ref="1040.line1a.wages",
        value=100000.0,
        raw_value="100000",
        source_doc_id=doc_one.id,
        source_locator="row:1",
        confidence=0.98,
        materiality=Materiality.MATERIAL,
        status=FactStatus.EXTRACTED,
    )
    fact_two = TaxFact(
        return_id=tax_return.id,
        tax_year=tax_return.tax_year,
        form_line_ref="1040.line25a.withholding",
        value=18000.0,
        raw_value="18000",
        source_doc_id=doc_two.id,
        source_locator="row:1",
        confidence=0.97,
        materiality=Materiality.MATERIAL,
        status=FactStatus.EXTRACTED,
    )
    session.add(fact_one)
    session.add(fact_two)
    session.commit()
    session.refresh(fact_one)
    session.refresh(fact_two)

    session.add(
        EvidenceLink(
            fact_id=fact_one.id,
            doc_id=doc_one.id,
            extraction_method="csv-direct",
            checksum=doc_one.sha256,
        )
    )
    session.add(
        Attestation(
            return_id=tax_return.id,
            fact_id=fact_two.id,
            actor_id="taxpayer-1",
            rationale="User confirms withholding from official portal.",
        )
    )
    session.commit()

    readiness = evaluate_readiness(session, test_settings, tax_return.id)
    assert readiness.material_fields_total == 2
    assert readiness.evidenced_or_attested == 2
    assert readiness.evidence_coverage_pct == 100.0
    assert readiness.ready_to_file is True


def test_generate_scenarios_returns_ranked_results_and_replaces_previous(session):
    tax_return = _create_return(session, filing_status=FilingStatus.SINGLE)

    session.add_all(
        [
            TaxFact(
                return_id=tax_return.id,
                tax_year=tax_return.tax_year,
                form_line_ref="1040.line1a.wages",
                value=120000.0,
                raw_value="120000",
                source_doc_id="doc-1",
                source_locator="row:1",
                confidence=0.98,
            ),
            TaxFact(
                return_id=tax_return.id,
                tax_year=tax_return.tax_year,
                form_line_ref="1040.line25a.withholding",
                value=25000.0,
                raw_value="25000",
                source_doc_id="doc-1",
                source_locator="row:2",
                confidence=0.98,
            ),
            TaxFact(
                return_id=tax_return.id,
                tax_year=tax_return.tax_year,
                form_line_ref="schedule_a.mortgage_interest",
                value=6000.0,
                raw_value="6000",
                source_doc_id="doc-2",
                source_locator="row:1",
                confidence=0.97,
            ),
        ]
    )
    session.commit()

    scenarios = generate_scenarios(session, tax_return.id, include_itemized=True)
    names = {scenario.name for scenario in scenarios}
    assert "standard_deduction" in names
    assert "itemized_not_beneficial" in names
    assert [scenario.rank for scenario in scenarios] == list(range(1, len(scenarios) + 1))

    rerun = generate_scenarios(session, tax_return.id, include_itemized=False)
    rerun_names = {scenario.name for scenario in rerun}
    assert "itemized_deduction" not in rerun_names
    assert "itemized_not_beneficial" not in rerun_names
    assert "standard_deduction" in rerun_names


def test_build_freetaxusa_export_uses_highest_confidence_fact_and_latest_approval(session, test_settings):
    tax_return = _create_return(session)
    wages_doc = _create_document(session, return_id=tax_return.id, file_name="w2.csv", doc_type="w2")
    wages_doc_alt = _create_document(session, return_id=tax_return.id, file_name="w2_alt.csv", doc_type="w2")
    withholding_doc = _create_document(session, return_id=tax_return.id, file_name="withholding.csv", doc_type="w2")

    wages_low = TaxFact(
        return_id=tax_return.id,
        tax_year=tax_return.tax_year,
        form_line_ref="1040.line1a.wages",
        value=110000.0,
        raw_value="110000",
        source_doc_id=wages_doc.id,
        source_locator="row:1",
        confidence=0.82,
    )
    wages_high = TaxFact(
        return_id=tax_return.id,
        tax_year=tax_return.tax_year,
        form_line_ref="1040.line1a.wages",
        value=110000.0,
        raw_value="110000",
        source_doc_id=wages_doc_alt.id,
        source_locator="row:1",
        confidence=0.96,
    )
    withholding = TaxFact(
        return_id=tax_return.id,
        tax_year=tax_return.tax_year,
        form_line_ref="1040.line25a.withholding",
        value=20000.0,
        raw_value="20000",
        source_doc_id=withholding_doc.id,
        source_locator="row:2",
        confidence=0.99,
    )
    session.add(wages_low)
    session.add(wages_high)
    session.add(withholding)
    session.commit()
    session.refresh(wages_low)
    session.refresh(wages_high)
    session.refresh(withholding)

    session.add_all(
        [
            EvidenceLink(
                fact_id=wages_low.id,
                doc_id=wages_doc.id,
                extraction_method="csv-direct",
                checksum=wages_doc.sha256,
            ),
            EvidenceLink(
                fact_id=wages_high.id,
                doc_id=wages_doc_alt.id,
                extraction_method="csv-direct",
                checksum=wages_doc_alt.sha256,
            ),
            EvidenceLink(
                fact_id=withholding.id,
                doc_id=withholding_doc.id,
                extraction_method="csv-direct",
                checksum=withholding_doc.sha256,
            ),
        ]
    )

    session.add_all(
        [
            ApprovalEvent(
                return_id=tax_return.id,
                role=ApprovalRole.TAXPAYER,
                actor_id="taxpayer-1",
                decision=ApprovalDecision.APPROVED,
                notes="Initial review complete.",
                created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            ApprovalEvent(
                return_id=tax_return.id,
                role=ApprovalRole.TAXPAYER,
                actor_id="taxpayer-2",
                decision=ApprovalDecision.REJECTED,
                notes="Need one correction.",
                created_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5),
            ),
        ]
    )
    session.commit()

    payload = build_freetaxusa_export(session, test_settings, tax_return.id)
    fields_by_key = {item["field_key"]: item for item in payload["fields"]}

    assert fields_by_key["federal.wages"]["fact_id"] == wages_high.id
    assert fields_by_key["federal.withholding"]["value"] == 20000.0

    approvals = payload["audit_summary"]["approvals"]
    assert approvals["taxpayer"]["decision"] == "rejected"


def test_local_storage_backend_round_trip(tmp_path: Path):
    settings = Settings(storage_backend="local", storage_dir=str(tmp_path / "uploads"))
    storage = build_object_storage(settings)
    key = build_storage_key(tax_year=2025, return_id="ret-1", digest="abc123", extension=".csv")

    stored = storage.store_bytes(key, b"hello-tax")
    assert stored.location.startswith("file://")
    assert storage.exists(stored.location)
    assert storage.read_bytes(stored.location) == b"hello-tax"

    storage.delete(stored.location)
    assert not storage.exists(stored.location)


def test_mapping_override_status_transitions(session):
    assert effective_mapping_status(session, "1040.line1a.wages") == MappingStatus.VERIFIED

    set_mapping_override(
        session,
        canonical_fact_ref="1040.line1a.wages",
        status=MappingStatus.UNVERIFIED,
        actor_id="cpa-1",
        reason="Drift found in filing season update.",
    )
    assert effective_mapping_status(session, "1040.line1a.wages") == MappingStatus.UNVERIFIED

    set_mapping_override(
        session,
        canonical_fact_ref="1040.line1a.wages",
        status=MappingStatus.VERIFIED,
        actor_id="cpa-1",
        reason="Row revalidated against current FreeTaxUSA flow.",
    )
    assert effective_mapping_status(session, "1040.line1a.wages") == MappingStatus.VERIFIED


def test_apply_retention_policy_removes_old_return_artifacts(session, tmp_path: Path):
    settings = Settings(
        storage_backend="local",
        storage_dir=str(tmp_path / "uploads"),
        retention_days=30,
    )
    settings.ensure_paths()
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(days=120)

    stale_return = TaxReturn(
        tax_year=2023,
        primary_state="NY",
        filing_status=FilingStatus.SINGLE,
        created_at=stale_time,
        updated_at=stale_time,
    )
    active_return = TaxReturn(
        tax_year=2025,
        primary_state="NY",
        filing_status=FilingStatus.MFJ,
        created_at=now,
        updated_at=now,
    )
    session.add(stale_return)
    session.add(active_return)
    session.commit()
    session.refresh(stale_return)
    session.refresh(active_return)

    storage = build_object_storage(settings)
    stale_payload = storage.store_bytes(
        build_storage_key(tax_year=2023, return_id=stale_return.id, digest="retention-old", extension=".csv"),
        b"form_line_ref,value\n1040.line1a.wages,50000\n",
    )

    stale_doc = Document(
        return_id=stale_return.id,
        file_name="old_w2.csv",
        content_type="text/csv",
        source_type=SourceType.CSV,
        quality_tier=DocumentQuality.OFFICIAL,
        sha256="retention-old",
        storage_path=stale_payload.location,
        classification_status="classified",
        doc_type="w2",
        tax_year=2023,
        owner="taxpayer",
        created_at=stale_time,
    )
    session.add(stale_doc)
    session.commit()
    session.refresh(stale_doc)

    stale_fact = TaxFact(
        return_id=stale_return.id,
        tax_year=2023,
        form_line_ref="1040.line1a.wages",
        value=50000.0,
        raw_value="50000",
        source_doc_id=stale_doc.id,
        source_locator="row:1",
        confidence=0.98,
        materiality=Materiality.MATERIAL,
        status=FactStatus.EXTRACTED,
    )
    session.add(stale_fact)
    session.commit()
    session.refresh(stale_fact)

    session.add(
        EvidenceLink(
            fact_id=stale_fact.id,
            doc_id=stale_doc.id,
            extraction_method="csv-direct",
            checksum=stale_doc.sha256,
        )
    )
    session.commit()

    result = apply_retention_policy(session, settings, now=now)
    assert result.returns_deleted == 1
    assert result.documents_deleted == 1
    assert result.storage_objects_deleted == 1

    assert session.get(TaxReturn, stale_return.id) is None
    assert session.get(TaxReturn, active_return.id) is not None
    assert not storage.exists(stale_payload.location)
