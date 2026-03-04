# API Contract (Tax Assistant MVP)

Base path: `/v1`

## Health + Client
- `GET /healthz`
- `GET /v1/client-config`

## Returns
- `POST /v1/returns`
  - body: `{ "tax_year": 2025, "primary_state": "NY", "filing_status": "mfj|single|mfs|hoh" }`
  - response: `{ "id", "tax_year", "primary_state", "filing_status", "status", "created_at" }`
- `GET /v1/returns/{return_id}/documents`
- `POST /v1/returns/{return_id}/extract-all`
  - body: `{ "force": false }`
- `GET /v1/returns/{return_id}/facts`
- `GET /v1/returns/{return_id}/issues`
- `GET /v1/returns/{return_id}/readiness`
- `POST /v1/returns/{return_id}/optimize`
  - body: `{ "include_itemized": true }`
- `POST /v1/returns/{return_id}/attest`
  - auth: actor identity via header mode (`X-User-Id`, `X-Role`) or bearer mode (`Authorization: Bearer ...`)
  - body: `{ "fact_id": "...", "rationale": "..." }`
- `POST /v1/returns/{return_id}/approve`
  - auth: actor identity via header mode or bearer mode
  - body: `{ "decision": "approved|rejected", "notes": "..." }`
- `GET /v1/returns/{return_id}/export/freetaxusa`

## Documents
- `POST /v1/documents/upload` (`multipart/form-data`)
  - fields: `return_id`, `tax_year`, `owner`, `source_type`, `file`
- `POST /v1/documents/{document_id}/extract`

## Issues (Manual lifecycle)
- `POST /v1/issues/{issue_id}/resolve`
  - auth: actor identity, role `cpa`
  - body: `{ "note": "..." }`
- `POST /v1/issues/{issue_id}/reopen`
  - auth: actor identity, role `cpa`
  - body: `{ "note": "..." }`

## FreeTaxUSA Mapping Lifecycle
- `GET /v1/mappings/freetaxusa`
- `POST /v1/mappings/freetaxusa/overrides`
  - auth: actor identity, role `cpa`
  - body: `{ "canonical_fact_ref": "...", "status": "verified|unverified", "reason": "..." }`

## Retention Admin
- `POST /v1/admin/retention/run`
  - auth: actor identity, role `cpa`

## Authorization rules
- Endpoints that mutate approvals/attestations/issues/mapping/retention require authenticated actor identity.
- `TAX_ASSISTANT_AUTH_MODE=header` uses `X-User-Id` and `X-Role`.
- `TAX_ASSISTANT_AUTH_MODE=bearer` validates JWTs via `TAX_ASSISTANT_AUTH_JWKS_URL` or `TAX_ASSISTANT_AUTH_JWT_SECRET`.
- CPA role is required for issue lifecycle, mapping overrides, and retention execution.
