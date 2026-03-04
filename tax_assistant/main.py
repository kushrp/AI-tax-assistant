from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from tax_assistant.api.routes import router as v1_router
from tax_assistant.config import Settings, get_settings
from tax_assistant.db import build_engine, init_db
from tax_assistant.models import TaxReturn
from tax_assistant.schemas import HealthResponse
from tax_assistant.services.retention_service import apply_retention_policy


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(app_settings)
        init_db(engine)
        app.state.settings = app_settings
        app.state.engine = engine
        with Session(engine) as session:
            apply_retention_policy(session, app_settings)
        yield

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    if app_settings.parsed_cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.parsed_cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(v1_router, prefix="/v1")

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/app", include_in_schema=False)
    def app_shell() -> HTMLResponse:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        api_base_script = (
            "<script>"
            f"window.TAX_ASSISTANT_API_BASE_URL = {json.dumps(app_settings.normalized_api_base_url)};"
            "</script>"
        )
        html = html.replace("</head>", f"  {api_base_script}\n  </head>")
        return HTMLResponse(html)

    @app.get("/healthz", response_model=HealthResponse)
    def healthz(request: Request) -> HealthResponse:
        engine = request.app.state.engine
        try:
            with Session(engine) as session:
                session.exec(select(TaxReturn.id).limit(1)).first()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return HealthResponse(status="ok", database="ok")

    return app


app = create_app()
