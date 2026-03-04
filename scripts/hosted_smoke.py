#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
from typing import Any

import httpx


def run_hosted_smoke(
    *,
    app_base_url: str,
    api_base_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    app_base = app_base_url.rstrip("/")
    api_base = api_base_url.rstrip("/")

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        health = client.get(f"{api_base}/healthz")
        health.raise_for_status()
        _expect(health.json().get("status") == "ok", "healthz did not report status=ok")

        shell = client.get(f"{app_base}/app")
        shell.raise_for_status()
        _expect("Collaborative Filing Inbox" in shell.text, "UI shell missing expected title")

        create_return = client.post(
            f"{api_base}/v1/returns",
            json={
                "tax_year": 2025,
                "primary_state": "NY",
                "filing_status": "mfj",
            },
        )
        create_return.raise_for_status()
        return_id = create_return.json()["id"]

        document_csv = (
            "form_line_ref,value\n"
            "1040.line1a.wages,120000\n"
            "1040.line25a.withholding,22000\n"
            "ny.it201.line1.wages,120000\n"
            "ny.it201.line33.new_york_adjusted_gross_income,119000\n"
            "ny.it201.line37.new_york_taxable_income,105000\n"
            "ny.it201.line46.new_york_state_tax,6200\n"
            "ny.it201.line61.new_york_state_withholding,6500\n"
        )
        upload = client.post(
            f"{api_base}/v1/documents/upload",
            data={
                "return_id": return_id,
                "tax_year": "2025",
                "owner": "taxpayer",
                "source_type": "csv",
            },
            files={
                "file": ("federal_ny_flow.csv", io.BytesIO(document_csv.encode("utf-8")), "text/csv"),
            },
        )
        upload.raise_for_status()
        document_id = upload.json()["document_id"]

        extract = client.post(f"{api_base}/v1/documents/{document_id}/extract")
        extract.raise_for_status()

        issues = client.get(f"{api_base}/v1/returns/{return_id}/issues")
        issues.raise_for_status()

        readiness = client.get(f"{api_base}/v1/returns/{return_id}/readiness")
        readiness.raise_for_status()
        readiness_payload = readiness.json()
        _expect(readiness_payload["ready_to_file"] is True, "readiness did not return ready_to_file=true")

        optimize = client.post(
            f"{api_base}/v1/returns/{return_id}/optimize",
            json={"include_itemized": True},
        )
        optimize.raise_for_status()
        _expect(len(optimize.json().get("scenarios", [])) >= 1, "optimize did not produce scenarios")

        export = client.get(f"{api_base}/v1/returns/{return_id}/export/freetaxusa")
        export.raise_for_status()
        export_payload = export.json()
        fields = {entry["field_key"]: entry["value"] for entry in export_payload["fields"]}
        for key in (
            "federal.wages",
            "federal.withholding",
            "state.ny.wages",
            "state.ny.adjusted_gross_income",
            "state.ny.taxable_income",
            "state.ny.tax",
            "state.ny.withholding",
        ):
            _expect(key in fields, f"missing export key: {key}")

        return {
            "return_id": return_id,
            "issues_open": len(issues.json()),
            "readiness": readiness_payload,
            "export_field_count": len(export_payload["fields"]),
            "state_keys_present": sorted([k for k in fields if k.startswith("state.ny.")]),
        }


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run hosted smoke validation against a deployed Tax Assistant environment.",
    )
    parser.add_argument("--base-url", required=True, help="Hosted base URL (for Railway or Vercel origin).")
    parser.add_argument(
        "--api-base-url",
        default="",
        help="Optional API origin when UI and API are split. Defaults to --base-url.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout for each request.")
    args = parser.parse_args()

    api_base_url = args.api_base_url or args.base_url
    result = run_hosted_smoke(
        app_base_url=args.base_url,
        api_base_url=api_base_url,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
