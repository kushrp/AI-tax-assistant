from __future__ import annotations

import io
import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tax_assistant.config import Settings
from tax_assistant.main import create_app
from tax_assistant.models import Document
from tax_assistant.services.storage_service import build_object_storage

pytestmark = pytest.mark.integration


def _live_s3_settings(tmp_path) -> Settings:
    if os.getenv("RUN_LIVE_S3_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_S3_TESTS=1 to execute live S3 integration tests.")

    bucket = os.getenv("TAX_ASSISTANT_LIVE_S3_BUCKET", "").strip()
    if not bucket:
        pytest.skip("TAX_ASSISTANT_LIVE_S3_BUCKET is required for live S3 integration tests.")

    return Settings(
        database_url=f"sqlite:///{tmp_path / 's3_live_test.db'}",
        storage_backend="s3",
        storage_bucket=bucket,
        storage_prefix=os.getenv("TAX_ASSISTANT_LIVE_S3_PREFIX", "tax-assistant-live-tests"),
        storage_endpoint_url=os.getenv("TAX_ASSISTANT_LIVE_S3_ENDPOINT_URL") or None,
        storage_region=os.getenv("TAX_ASSISTANT_LIVE_S3_REGION") or None,
        storage_access_key_id=os.getenv("TAX_ASSISTANT_LIVE_S3_ACCESS_KEY_ID") or None,
        storage_secret_access_key=os.getenv("TAX_ASSISTANT_LIVE_S3_SECRET_ACCESS_KEY") or None,
    )


def test_live_s3_round_trip_upload_extract_export(tmp_path):
    settings = _live_s3_settings(tmp_path)
    app = create_app(settings)

    try:
        with TestClient(app) as client:
            created = client.post(
                "/v1/returns",
                json={"tax_year": 2025, "primary_state": "NY", "filing_status": "mfj"},
            )
            assert created.status_code == 200, created.text
            return_id = created.json()["id"]

            csv_payload = (
                "form_line_ref,value\n"
                "1040.line1a.wages,101000\n"
                "1040.line25a.withholding,18000\n"
                "ny.it201.line1.wages,101000\n"
                "ny.it201.line46.new_york_state_tax,5000\n"
                "ny.it201.line61.new_york_state_withholding,5400\n"
            )
            upload = client.post(
                "/v1/documents/upload",
                data={
                    "return_id": return_id,
                    "tax_year": "2025",
                    "owner": "taxpayer",
                    "source_type": "csv",
                },
                files={
                    "file": ("live_s3_round_trip.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv"),
                },
            )
            assert upload.status_code == 200, upload.text
            document_id = upload.json()["document_id"]

            extract = client.post(f"/v1/documents/{document_id}/extract")
            assert extract.status_code == 200, extract.text

            export = client.get(f"/v1/returns/{return_id}/export/freetaxusa")
            assert export.status_code == 200, export.text
            field_keys = {item["field_key"] for item in export.json()["fields"]}
            assert "state.ny.wages" in field_keys
            assert "state.ny.tax" in field_keys
            assert "state.ny.withholding" in field_keys
    finally:
        storage = build_object_storage(settings)
        with Session(app.state.engine) as session:
            documents = list(session.exec(select(Document)))
            for document in documents:
                if storage.exists(document.storage_path):
                    storage.delete(document.storage_path)
