from __future__ import annotations

import io

from fastapi.testclient import TestClient
import jwt

from tax_assistant.config import Settings
from tax_assistant.main import create_app


def create_return(client, *, tax_year: int = 2025, primary_state: str = "NY", filing_status: str = "mfj") -> dict:
    response = client.post(
        "/v1/returns",
        json={
            "tax_year": tax_year,
            "primary_state": primary_state,
            "filing_status": filing_status,
        },
    )
    assert response.status_code == 200
    return response.json()


def upload_doc(
    client,
    return_id: str,
    *,
    filename: str,
    content: bytes,
    source_type: str = "csv",
    tax_year: int = 2025,
    content_type: str = "text/csv",
):
    data = {
        "return_id": return_id,
        "tax_year": str(tax_year),
        "owner": "taxpayer",
        "source_type": source_type,
    }
    files = {"file": (filename, io.BytesIO(content), content_type)}
    return client.post("/v1/documents/upload", data=data, files=files)


def extract_doc(client, doc_id: str) -> dict:
    response = client.post(f"/v1/documents/{doc_id}/extract")
    assert response.status_code == 200
    return response.json()


def bearer_token(user_id: str, role: str, *, secret: str) -> str:
    return jwt.encode({"sub": user_id, "role": role}, secret, algorithm="HS256")


def test_healthz_and_app_shell_routes(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "ok"}

    shell = client.get("/app")
    assert shell.status_code == 200
    assert "text/html" in shell.headers["content-type"]
    assert "Collaborative Filing Inbox" in shell.text
    assert "window.TAX_ASSISTANT_API_BASE_URL" in shell.text

    config = client.get("/v1/client-config")
    assert config.status_code == 200
    assert "api_base_url" in config.json()


def test_create_return_normalizes_state_and_rejects_invalid_state(client):
    created = create_return(client, primary_state="ny", filing_status="single")
    assert created["primary_state"] == "NY"
    assert created["filing_status"] == "single"

    invalid = client.post(
        "/v1/returns",
        json={"tax_year": 2025, "primary_state": "New York", "filing_status": "mfj"},
    )
    assert invalid.status_code == 422


def test_document_upload_validation_and_deduplication(client):
    missing_return_upload = upload_doc(
        client,
        "missing-return",
        filename="w2.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,100000\n",
    )
    assert missing_return_upload.status_code == 404

    created = create_return(client)
    return_id = created["id"]

    invalid_source_upload = upload_doc(
        client,
        return_id,
        filename="w2.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,100000\n",
        source_type="fax",
    )
    assert invalid_source_upload.status_code == 400
    assert "Invalid source_type" in invalid_source_upload.json()["detail"]

    first = upload_doc(
        client,
        return_id,
        filename="w2.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,100000\n",
    )
    second = upload_doc(
        client,
        return_id,
        filename="w2-copy.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,100000\n",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["duplicate"] is False
    assert second_payload["duplicate"] is True
    assert second_payload["document_id"] == first_payload["document_id"]


def test_document_listing_and_extract_all_skip_force_behavior(client):
    return_id = create_return(client)["id"]
    first = upload_doc(
        client,
        return_id,
        filename="w2.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,100000\n1040.line25a.withholding,19000\n",
    )
    second = upload_doc(
        client,
        return_id,
        filename="1099_int.csv",
        content=b"form_line_ref,value\n1040.line2b.taxable_interest,650\n",
    )
    assert first.status_code == 200
    assert second.status_code == 200

    listed_before = client.get(f"/v1/returns/{return_id}/documents")
    assert listed_before.status_code == 200
    docs_before = listed_before.json()
    assert len(docs_before) == 2
    assert all(item["latest_extraction_status"] is None for item in docs_before)
    assert all(item["facts_extracted"] == 0 for item in docs_before)

    first_extract_all = client.post(f"/v1/returns/{return_id}/extract-all", json={"force": False})
    assert first_extract_all.status_code == 200
    first_batch = first_extract_all.json()
    assert first_batch["processed"] == 2
    assert first_batch["succeeded"] == 2
    assert first_batch["skipped"] == 0
    assert first_batch["failed"] == 0
    assert all(item["status"] == "completed" for item in first_batch["documents"])

    listed_after = client.get(f"/v1/returns/{return_id}/documents")
    assert listed_after.status_code == 200
    docs_after = listed_after.json()
    assert all(item["latest_extraction_status"] == "completed" for item in docs_after)
    assert sum(item["facts_extracted"] for item in docs_after) == 3

    second_extract_all = client.post(f"/v1/returns/{return_id}/extract-all", json={"force": False})
    assert second_extract_all.status_code == 200
    second_batch = second_extract_all.json()
    assert second_batch["processed"] == 2
    assert second_batch["succeeded"] == 0
    assert second_batch["skipped"] == 2
    assert second_batch["failed"] == 0
    assert all(item["status"] == "skipped" for item in second_batch["documents"])

    forced_extract_all = client.post(f"/v1/returns/{return_id}/extract-all", json={"force": True})
    assert forced_extract_all.status_code == 200
    forced_batch = forced_extract_all.json()
    assert forced_batch["processed"] == 2
    assert forced_batch["succeeded"] == 2
    assert forced_batch["skipped"] == 0
    assert forced_batch["failed"] == 0


def test_golden_csv_flow_allows_export(client):
    return_id = create_return(client)["id"]
    uploaded = upload_doc(
        client,
        return_id,
        filename="w2_2025.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,120000\n1040.line25a.withholding,22000\n",
    )
    assert uploaded.status_code == 200

    extraction = extract_doc(client, uploaded.json()["document_id"])
    assert extraction["extracted_facts"] == 2

    facts = client.get(f"/v1/returns/{return_id}/facts")
    assert facts.status_code == 200
    refs = {item["form_line_ref"] for item in facts.json()}
    assert refs == {"1040.line1a.wages", "1040.line25a.withholding"}

    readiness = client.get(f"/v1/returns/{return_id}/readiness")
    assert readiness.status_code == 200
    readiness_payload = readiness.json()
    assert readiness_payload["ready_to_file"] is True
    assert readiness_payload["open_blocking_issues"] == 0
    assert readiness_payload["evidence_coverage_pct"] == 100.0

    export = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert export.status_code == 200
    keys = {item["field_key"] for item in export.json()["fields"]}
    assert "federal.wages" in keys
    assert "federal.withholding" in keys


def test_federal_and_ny_state_flow_exports_expected_state_fields(client):
    return_id = create_return(client, primary_state="NY")["id"]
    uploaded = upload_doc(
        client,
        return_id,
        filename="federal_ny.csv",
        content=(
            b"form_line_ref,value\n"
            b"1040.line1a.wages,125000\n"
            b"1040.line25a.withholding,23000\n"
            b"ny.it201.line1.wages,125000\n"
            b"ny.it201.line33.new_york_adjusted_gross_income,122500\n"
            b"ny.it201.line37.new_york_taxable_income,109200\n"
            b"ny.it201.line46.new_york_state_tax,6400\n"
            b"ny.it201.line61.new_york_state_withholding,6800\n"
        ),
    )
    assert uploaded.status_code == 200

    extraction = extract_doc(client, uploaded.json()["document_id"])
    assert extraction["extracted_facts"] == 7

    readiness = client.get(f"/v1/returns/{return_id}/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["ready_to_file"] is True

    export = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert export.status_code == 200
    fields = {item["field_key"]: item["value"] for item in export.json()["fields"]}
    assert fields["federal.wages"] == 125000.0
    assert fields["federal.withholding"] == 23000.0
    assert fields["state.ny.wages"] == 125000.0
    assert fields["state.ny.adjusted_gross_income"] == 122500.0
    assert fields["state.ny.taxable_income"] == 109200.0
    assert fields["state.ny.tax"] == 6400.0
    assert fields["state.ny.withholding"] == 6800.0


def test_conflicting_values_create_blocking_issue_and_block_export(client):
    return_id = create_return(client)["id"]
    first = upload_doc(
        client,
        return_id,
        filename="w2_a.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,100000\n",
    )
    second = upload_doc(
        client,
        return_id,
        filename="w2_b.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,120000\n",
    )
    extract_doc(client, first.json()["document_id"])
    extract_doc(client, second.json()["document_id"])

    issues = client.get(f"/v1/returns/{return_id}/issues")
    assert issues.status_code == 200
    payload = issues.json()
    assert any(item["category"] == "system.conflict.values" and item["blocking"] for item in payload)

    blocked_export = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert blocked_export.status_code == 400
    detail = blocked_export.json()["detail"]
    assert detail["message"] == "Return is not ready to file"
    assert detail["readiness"]["open_blocking_issues"] >= 1


def test_missing_prior_8606_blocks_then_clears_after_prior_upload(client):
    return_id = create_return(client)["id"]

    roth = upload_doc(
        client,
        return_id,
        filename="1099-r-roth.csv",
        content=(
            b"form_line_ref,value\n"
            b"roth.conversion.amount,7000\n"
            b"1040.line4a.ira_distributions,7000\n"
            b"1040.line4b.taxable_ira,7000\n"
        ),
    )
    extract_doc(client, roth.json()["document_id"])

    blocked = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert blocked.status_code == 400
    assert any("8606" in title for title in blocked.json()["detail"]["readiness"]["blockers"])

    prior_8606 = upload_doc(
        client,
        return_id,
        filename="form8606_prior.csv",
        content=b"form_line_ref,value\nnotes.8606_present,1\n",
        tax_year=2024,
    )
    extract_doc(client, prior_8606.json()["document_id"])

    issues = client.get(f"/v1/returns/{return_id}/issues")
    assert issues.status_code == 200
    assert not any(item["category"] == "system.backdoor_roth.missing_8606" for item in issues.json())

    export = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert export.status_code == 200


def test_screenshot_extraction_creates_supplemental_and_low_confidence_blockers(client):
    return_id = create_return(client)["id"]
    screenshot = upload_doc(
        client,
        return_id,
        filename="wages_12000.png",
        content=b"not-a-real-image",
        source_type="screenshot",
        content_type="image/png",
    )
    extract_doc(client, screenshot.json()["document_id"])

    facts = client.get(f"/v1/returns/{return_id}/facts")
    assert facts.status_code == 200
    assert any(f["form_line_ref"] == "1040.line1a.wages" for f in facts.json())

    issues = client.get(f"/v1/returns/{return_id}/issues")
    assert issues.status_code == 200
    categories = {item["category"] for item in issues.json()}
    assert "system.evidence.supplemental_only" in categories
    assert "system.evidence.low_confidence" in categories


def test_attest_and_approve_flow_updates_summary_and_invalid_role_is_rejected(client):
    return_id = create_return(client)["id"]
    screenshot = upload_doc(
        client,
        return_id,
        filename="wages_12000.png",
        content=b"fake-image",
        source_type="screenshot",
        content_type="image/png",
    )
    extract_doc(client, screenshot.json()["document_id"])

    fact_id = client.get(f"/v1/returns/{return_id}/facts").json()[0]["id"]

    attest = client.post(
        f"/v1/returns/{return_id}/attest",
        json={"fact_id": fact_id, "rationale": "Taxpayer confirms screenshot amount from issuing portal."},
        headers={"X-User-Id": "taxpayer-1", "X-Role": "taxpayer"},
    )
    assert attest.status_code == 200
    assert attest.json()["evidenced_or_attested"] >= 1

    issues_after_attest = client.get(f"/v1/returns/{return_id}/issues")
    categories = {item["category"] for item in issues_after_attest.json()}
    assert "system.evidence.low_confidence" not in categories
    assert "system.evidence.supplemental_only" in categories

    spouse_approval = client.post(
        f"/v1/returns/{return_id}/approve",
        json={"decision": "approved", "notes": "Reviewed by spouse."},
        headers={"X-User-Id": "spouse-1", "X-Role": "spouse"},
    )
    assert spouse_approval.status_code == 200
    assert spouse_approval.json()["summary"]["spouse"] == "approved"

    invalid_role = client.post(
        f"/v1/returns/{return_id}/approve",
        json={"decision": "approved", "notes": "Should fail."},
        headers={"X-User-Id": "reviewer-1", "X-Role": "reviewer"},
    )
    assert invalid_role.status_code == 400
    assert "Invalid role" in invalid_role.json()["detail"]


def test_unmapped_material_fact_blocks_export_with_mapping_issue(client):
    return_id = create_return(client)["id"]
    uploaded = upload_doc(
        client,
        return_id,
        filename="custom_facts.csv",
        content=(
            b"form_line_ref,value\n"
            b"1040.line1a.wages,110000\n"
            b"custom.income_adjustment,2500\n"
        ),
    )
    assert uploaded.status_code == 200
    extract_doc(client, uploaded.json()["document_id"])

    issues = client.get(f"/v1/returns/{return_id}/issues")
    assert issues.status_code == 200
    payload = issues.json()
    assert any(item["category"] == "system.export.unmapped_material_fields" and item["blocking"] for item in payload)

    readiness = client.get(f"/v1/returns/{return_id}/readiness")
    assert readiness.status_code == 200
    readiness_payload = readiness.json()
    assert readiness_payload["ready_to_file"] is False
    assert "Material facts missing FreeTaxUSA mapping" in readiness_payload["blockers"]

    blocked_export = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert blocked_export.status_code == 400


def test_mapping_override_lifecycle_blocks_then_unblocks_export(client):
    return_id = create_return(client)["id"]
    uploaded = upload_doc(
        client,
        return_id,
        filename="w2.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,118000\n1040.line25a.withholding,22000\n",
    )
    assert uploaded.status_code == 200
    extract_doc(client, uploaded.json()["document_id"])

    export_ready = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert export_ready.status_code == 200

    forbidden = client.post(
        "/v1/mappings/freetaxusa/overrides",
        json={"canonical_fact_ref": "1040.line1a.wages", "status": "unverified", "reason": "Drift detected."},
        headers={"X-User-Id": "taxpayer-1", "X-Role": "taxpayer"},
    )
    assert forbidden.status_code == 403

    unverify = client.post(
        "/v1/mappings/freetaxusa/overrides",
        json={"canonical_fact_ref": "1040.line1a.wages", "status": "unverified", "reason": "Drift detected."},
        headers={"X-User-Id": "cpa-1", "X-Role": "cpa"},
    )
    assert unverify.status_code == 200
    assert unverify.json()["status"] == "unverified"

    issues = client.get(f"/v1/returns/{return_id}/issues")
    assert issues.status_code == 200
    categories = {item["category"] for item in issues.json()}
    assert "system.export.unverified_mapping_fields" in categories

    blocked_export = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert blocked_export.status_code == 400

    verify = client.post(
        "/v1/mappings/freetaxusa/overrides",
        json={"canonical_fact_ref": "1040.line1a.wages", "status": "verified", "reason": "Revalidated."},
        headers={"X-User-Id": "cpa-1", "X-Role": "cpa"},
    )
    assert verify.status_code == 200
    assert verify.json()["status"] == "verified"

    export_after = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
    assert export_after.status_code == 200


def test_issue_lifecycle_requires_cpa_and_supports_resolve_reopen(client):
    return_id = create_return(client)["id"]
    first = upload_doc(
        client,
        return_id,
        filename="w2_a.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,100000\n",
    )
    second = upload_doc(
        client,
        return_id,
        filename="w2_b.csv",
        content=b"form_line_ref,value\n1040.line1a.wages,120000\n",
    )
    extract_doc(client, first.json()["document_id"])
    extract_doc(client, second.json()["document_id"])

    issues = client.get(f"/v1/returns/{return_id}/issues")
    assert issues.status_code == 200
    conflict_issue = next(item for item in issues.json() if item["category"] == "system.conflict.values")

    forbidden = client.post(
        f"/v1/issues/{conflict_issue['id']}/resolve",
        json={"note": "Taxpayer cannot close this."},
        headers={"X-User-Id": "taxpayer-1", "X-Role": "taxpayer"},
    )
    assert forbidden.status_code == 403

    resolved = client.post(
        f"/v1/issues/{conflict_issue['id']}/resolve",
        json={"note": "Resolved after source reconciliation."},
        headers={"X-User-Id": "cpa-1", "X-Role": "cpa"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    reopened = client.post(
        f"/v1/issues/{conflict_issue['id']}/reopen",
        json={"note": "Needs another review pass."},
        headers={"X-User-Id": "cpa-1", "X-Role": "cpa"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"


def test_attest_and_approve_require_authenticated_actor(client):
    return_id = create_return(client)["id"]
    screenshot = upload_doc(
        client,
        return_id,
        filename="wages_12000.png",
        content=b"fake-image",
        source_type="screenshot",
        content_type="image/png",
    )
    extract_doc(client, screenshot.json()["document_id"])

    fact_id = client.get(f"/v1/returns/{return_id}/facts").json()[0]["id"]

    attest_unauth = client.post(
        f"/v1/returns/{return_id}/attest",
        json={"fact_id": fact_id, "rationale": "Confirmed amount."},
    )
    assert attest_unauth.status_code == 401

    approve_unauth = client.post(
        f"/v1/returns/{return_id}/approve",
        json={"decision": "approved", "notes": "Looks good."},
    )
    assert approve_unauth.status_code == 401


def test_cors_preflight_allows_configured_origin(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'cors.db'}",
        storage_dir=str(tmp_path / "uploads"),
        cors_allowed_origins="https://ui.example",
    )
    app = create_app(settings)

    with TestClient(app) as local_client:
        response = local_client.options(
            "/v1/returns",
            headers={
                "Origin": "https://ui.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "https://ui.example"


def test_bearer_auth_mode_enforces_identity_and_role(tmp_path):
    shared_secret = "test-shared-secret-value-at-least-32-bytes"
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'bearer_auth.db'}",
        storage_dir=str(tmp_path / "uploads"),
        auth_mode="bearer",
        auth_jwt_secret=shared_secret,
        auth_allowed_algorithms="HS256",
    )
    app = create_app(settings)

    with TestClient(app) as local_client:
        return_id = create_return(local_client)["id"]
        uploaded = upload_doc(
            local_client,
            return_id,
            filename="w2.csv",
            content=b"form_line_ref,value\n1040.line1a.wages,98000\n1040.line25a.withholding,16000\n",
        )
        assert uploaded.status_code == 200
        extract_doc(local_client, uploaded.json()["document_id"])

        missing_token = local_client.post(
            "/v1/mappings/freetaxusa/overrides",
            json={"canonical_fact_ref": "1040.line1a.wages", "status": "unverified", "reason": "test"},
        )
        assert missing_token.status_code == 401

        taxpayer_token = bearer_token("taxpayer-1", "taxpayer", secret=shared_secret)
        forbidden = local_client.post(
            "/v1/mappings/freetaxusa/overrides",
            json={"canonical_fact_ref": "1040.line1a.wages", "status": "unverified", "reason": "test"},
            headers={"Authorization": f"Bearer {taxpayer_token}"},
        )
        assert forbidden.status_code == 403

        cpa_token = bearer_token("cpa-1", "cpa", secret=shared_secret)
        allowed = local_client.post(
            "/v1/mappings/freetaxusa/overrides",
            json={"canonical_fact_ref": "1040.line1a.wages", "status": "unverified", "reason": "test"},
            headers={"Authorization": f"Bearer {cpa_token}"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["updated_by"] == "cpa-1"


def test_bearer_auth_mode_rejects_invalid_token(tmp_path):
    valid_secret = "right-secret-value-at-least-32-bytes"
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'bearer_invalid.db'}",
        storage_dir=str(tmp_path / "uploads"),
        auth_mode="bearer",
        auth_jwt_secret=valid_secret,
        auth_allowed_algorithms="HS256",
    )
    app = create_app(settings)

    with TestClient(app) as local_client:
        return_id = create_return(local_client)["id"]
        uploaded = upload_doc(
            local_client,
            return_id,
            filename="w2.csv",
            content=b"form_line_ref,value\n1040.line1a.wages,98000\n",
        )
        extract_doc(local_client, uploaded.json()["document_id"])
        fact_id = local_client.get(f"/v1/returns/{return_id}/facts").json()[0]["id"]

        bad_token = bearer_token("taxpayer-1", "taxpayer", secret="wrong-secret-value-at-least-32-bytes")
        response = local_client.post(
            f"/v1/returns/{return_id}/attest",
            json={"fact_id": fact_id, "rationale": "Validated from source statement."},
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert response.status_code == 401
