# Deployment Guide (Free Tier)

This project currently ships as a single FastAPI service that includes both:
- API endpoints (`/v1/...`)
- web UI shell (`/app` + `/static/...`)

For the fastest free-tier path, deploy the whole app to Railway first.  
Vercel can be added later as a UI host that proxies API calls to Railway.

## 1. Environment Variables

Start from [`.env.example`](/Users/kushrustagi/projects/tax-assistant/.env.example).

Required now:
- `TAX_ASSISTANT_DATABASE_URL`
- `TAX_ASSISTANT_STORAGE_BACKEND`
- if local: `TAX_ASSISTANT_STORAGE_DIR`
- if s3: `TAX_ASSISTANT_STORAGE_BUCKET` (+ optional endpoint/credentials)

Optional:
- `TAX_ASSISTANT_APP_NAME`
- `TAX_ASSISTANT_RETENTION_DAYS`
- `TAX_ASSISTANT_MATERIAL_CONFIDENCE_THRESHOLD`
- `TAX_ASSISTANT_API_BASE_URL`
- `TAX_ASSISTANT_CORS_ALLOWED_ORIGINS`
- `TAX_ASSISTANT_REQUIRE_ACTOR_IDENTITY`
- `TAX_ASSISTANT_AUTH_MODE` (`header` or `bearer`)
- `TAX_ASSISTANT_AUTH_JWKS_URL` / `TAX_ASSISTANT_AUTH_JWT_SECRET` (when bearer auth is enabled)
- `TAX_ASSISTANT_AUTH_ISSUER`, `TAX_ASSISTANT_AUTH_AUDIENCE`, claim mapping vars

## 2. Local Container Smoke Test

```bash
docker build -t tax-assistant:local .
docker run --rm -p 8000:8000 --name tax-assistant tax-assistant:local
```

Verify:
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/docs`

## 3. Railway Deployment (Recommended First)

1. Create a Railway project from this repo.
2. Use the repository `Dockerfile` build path.
3. Set env vars from `.env.example`.
4. Keep `PORT` managed by Railway (the container command already reads it).
5. Set health check path to `/healthz`.
6. Deploy and open:
   - `https://<your-railway-domain>/app`
   - `https://<your-railway-domain>/docs`

Important notes:
- Local filesystem storage is supported for demos.
- S3-compatible object storage is supported for durable hosted deployments.
- Retention policy runs at app startup and can be run manually via `POST /v1/admin/retention/run` (CPA role required).

## 4. Vercel-Compatible UI Path (Optional)

Current UI JavaScript calls relative `/v1/...` endpoints, so host the UI on Vercel with rewrites that forward API routes to Railway.
If you host UI and API on separate origins without rewrites, set `TAX_ASSISTANT_API_BASE_URL` to the API origin and configure `TAX_ASSISTANT_CORS_ALLOWED_ORIGINS`.

Example `vercel.json` (if you split UI hosting):

```json
{
  "rewrites": [
    { "source": "/", "destination": "/tax_assistant/static/index.html" },
    { "source": "/static/:path*", "destination": "/tax_assistant/static/:path*" },
    { "source": "/v1/:path*", "destination": "https://YOUR-RAILWAY-DOMAIN/v1/:path*" },
    { "source": "/healthz", "destination": "https://YOUR-RAILWAY-DOMAIN/healthz" }
  ]
}
```

This keeps the browser on one origin and avoids CORS complexity for now.

## 5. Hosted Smoke Execution (Automated)

Run the hosted smoke runner against Railway or Vercel:

```bash
python scripts/hosted_smoke.py --base-url https://YOUR-HOST
```

If UI and API are split across origins:

```bash
python scripts/hosted_smoke.py \
  --base-url https://YOUR-VERCEL-ORIGIN \
  --api-base-url https://YOUR-RAILWAY-API-ORIGIN
```

The smoke script verifies:
1. `/healthz` and `/app`
2. return creation
3. upload + extraction
4. issues + readiness
5. optimize
6. export packet with federal + NY state field keys

## 6. Hosted Smoke in GitHub Actions

Workflow file: `.github/workflows/hosted-smoke.yml`

Options:
- manual run (`workflow_dispatch`) with `base_url` and optional `api_base_url`
- weekly scheduled run (uses repository secrets)

Secrets for scheduled mode:
- `TAX_ASSISTANT_SMOKE_BASE_URL`
- optional `TAX_ASSISTANT_SMOKE_API_BASE_URL`

## 7. Live S3 Integration Automation

Workflow file: `.github/workflows/live-s3-integration.yml`

This workflow runs `tests/test_s3_integration_live.py` against a real S3-compatible bucket when the
`TAX_ASSISTANT_LIVE_S3_BUCKET` secret is configured.
