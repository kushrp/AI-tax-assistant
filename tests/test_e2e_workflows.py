from __future__ import annotations

from fastapi.testclient import TestClient


def _create_return(client: TestClient, *, tax_year: int = 2025) -> str:
    response = client.post(
        "/v1/returns",
        json={
            "tax_year": tax_year,
            "primary_state": "NY",
            "filing_status": "mfj",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _upload_csv(
    client: TestClient,
    *,
    return_id: str,
    csv_body: str,
    file_name: str,
    source_type: str = "csv",
    tax_year: int = 2025,
    owner: str = "taxpayer",
) -> str:
    response = client.post(
        "/v1/documents/upload",
        data={
            "return_id": return_id,
            "tax_year": str(tax_year),
            "owner": owner,
            "source_type": source_type,
        },
        files={
            "file": (file_name, csv_body.encode("utf-8"), "text/csv"),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["document_id"]


def _extract(client: TestClient, document_id: str) -> None:
    response = client.post(f"/v1/documents/{document_id}/extract")
    assert response.status_code == 200, response.text


def _get_issues(client: TestClient, return_id: str) -> list[dict]:
    response = client.get(f"/v1/returns/{return_id}/issues")
    assert response.status_code == 200, response.text
    return response.json()


def _get_facts(client: TestClient, return_id: str) -> list[dict]:
    response = client.get(f"/v1/returns/{return_id}/facts")
    assert response.status_code == 200, response.text
    return response.json()


def _export(client: TestClient, return_id: str):
    return client.get(f"/v1/returns/{return_id}/export/freetaxusa")


def test_golden_flow_w2_csv_happy_path(client: TestClient) -> None:
    return_id = _create_return(client)

    ui_response = client.get("/app")
    assert ui_response.status_code == 200
    assert "Collaborative Filing Inbox" in ui_response.text

    script_response = client.get("/static/app.js")
    assert script_response.status_code == 200

    doc_id = _upload_csv(
        client,
        return_id=return_id,
        file_name="w2_income.csv",
        csv_body=(
            "form_line_ref,value\n"
            "1040.line1a.wages,125000\n"
            "1040.line25a.withholding,20000\n"
            "1040.line2b.taxable_interest,350\n"
            "schedule_a.charity,1500\n"
        ),
    )
    _extract(client, doc_id)

    facts = _get_facts(client, return_id)
    refs = {fact["form_line_ref"] for fact in facts}
    assert "1040.line1a.wages" in refs
    assert "1040.line25a.withholding" in refs

    issues = _get_issues(client, return_id)
    assert issues == []

    optimize_response = client.post(
        f"/v1/returns/{return_id}/optimize",
        json={"include_itemized": True},
    )
    assert optimize_response.status_code == 200, optimize_response.text
    scenarios = optimize_response.json()["scenarios"]
    assert len(scenarios) >= 2

    approve_response = client.post(
        f"/v1/returns/{return_id}/approve",
        headers={"x-user-id": "taxpayer-1", "x-role": "taxpayer"},
        json={"decision": "approved", "notes": "Looks good."},
    )
    assert approve_response.status_code == 200, approve_response.text

    readiness_response = client.get(f"/v1/returns/{return_id}/readiness")
    assert readiness_response.status_code == 200
    readiness = readiness_response.json()
    assert readiness["ready_to_file"] is True
    assert readiness["open_blocking_issues"] == 0

    export_response = _export(client, return_id)
    assert export_response.status_code == 200, export_response.text
    payload = export_response.json()

    assert payload["ready_to_file"] is True
    keys = {field["field_key"] for field in payload["fields"]}
    assert "federal.wages" in keys
    assert "federal.withholding" in keys
    assert payload["unresolved_question_queue"] == []
    assert "federal.wages" in payload["evidence_report"]
    assert payload["audit_summary"]["approvals"]["taxpayer"]["decision"] == "approved"


def test_conflicting_values_issue_blocks_export(client: TestClient) -> None:
    return_id = _create_return(client)

    doc1 = _upload_csv(
        client,
        return_id=return_id,
        file_name="w2_a.csv",
        csv_body="form_line_ref,value\n1040.line1a.wages,90000\n1040.line25a.withholding,15000\n",
    )
    doc2 = _upload_csv(
        client,
        return_id=return_id,
        file_name="w2_b.csv",
        csv_body="form_line_ref,value\n1040.line1a.wages,91000\n1040.line25a.withholding,15000\n",
    )

    _extract(client, doc1)
    _extract(client, doc2)

    issues = _get_issues(client, return_id)
    conflict_issues = [issue for issue in issues if issue["category"] == "system.conflict.values"]
    assert conflict_issues
    assert any(issue["blocking"] for issue in conflict_issues)

    export_response = _export(client, return_id)
    assert export_response.status_code == 400
    assert export_response.json()["detail"]["message"] == "Return is not ready to file"


def test_missing_8606_is_blocking_issue(client: TestClient) -> None:
    return_id = _create_return(client)

    doc_id = _upload_csv(
        client,
        return_id=return_id,
        file_name="ira_conversion.csv",
        csv_body=(
            "form_line_ref,value\n"
            "1040.line1a.wages,100000\n"
            "1040.line25a.withholding,12000\n"
            "roth.conversion.amount,6500\n"
            "1040.line4a.ira_distributions,6500\n"
            "1040.line4b.taxable_ira,6500\n"
        ),
    )
    _extract(client, doc_id)

    issues = _get_issues(client, return_id)
    assert any(issue["category"] == "system.backdoor_roth.missing_8606" and issue["blocking"] for issue in issues)

    export_response = _export(client, return_id)
    assert export_response.status_code == 400
    blockers = export_response.json()["detail"]["readiness"]["blockers"]
    assert "Missing prior-year Form 8606" in blockers


def test_screenshot_only_evidence_creates_blocker(client: TestClient) -> None:
    return_id = _create_return(client)

    doc_id = _upload_csv(
        client,
        return_id=return_id,
        file_name="screenshot_income.csv",
        source_type="screenshot",
        csv_body="form_line_ref,value\n1040.line1a.wages,76000\n1040.line25a.withholding,10000\n",
    )
    _extract(client, doc_id)

    issues = _get_issues(client, return_id)
    assert any(
        issue["category"] == "system.evidence.supplemental_only" and issue["blocking"]
        for issue in issues
    )

    readiness_response = client.get(f"/v1/returns/{return_id}/readiness")
    assert readiness_response.status_code == 200
    readiness = readiness_response.json()
    assert readiness["ready_to_file"] is False
    assert "Material fields supported only by screenshots/photos" in readiness["blockers"]


def test_export_gate_blocks_then_passes_after_resolving_blocker(client: TestClient) -> None:
    return_id = _create_return(client)

    conversion_doc = _upload_csv(
        client,
        return_id=return_id,
        file_name="conversion_1099r.csv",
        csv_body=(
            "form_line_ref,value\n"
            "1040.line1a.wages,115000\n"
            "1040.line25a.withholding,19000\n"
            "roth.conversion.amount,7000\n"
            "1040.line4a.ira_distributions,7000\n"
            "1040.line4b.taxable_ira,7000\n"
        ),
    )
    _extract(client, conversion_doc)

    blocked_export = _export(client, return_id)
    assert blocked_export.status_code == 400
    assert blocked_export.json()["detail"]["readiness"]["ready_to_file"] is False

    facts = _get_facts(client, return_id)
    attest_response = client.post(
        f"/v1/returns/{return_id}/attest",
        headers={"x-user-id": "taxpayer-1", "x-role": "taxpayer"},
        json={"fact_id": facts[0]["id"], "rationale": "Validated against source account statement."},
    )
    assert attest_response.status_code == 200, attest_response.text

    still_blocked = _export(client, return_id)
    assert still_blocked.status_code == 400

    _upload_csv(
        client,
        return_id=return_id,
        file_name="prior_year_8606.csv",
        tax_year=2024,
        csv_body="form_line_ref,value\nnotes.info,1\n",
    )

    ready_export = _export(client, return_id)
    assert ready_export.status_code == 200, ready_export.text
    payload = ready_export.json()
    assert payload["ready_to_file"] is True
    assert payload["unresolved_question_queue"] == []
    assert any(field["field_key"] == "retirement.roth_conversion" for field in payload["fields"])
