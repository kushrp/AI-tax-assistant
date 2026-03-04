from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from tax_assistant.api.routes import router as v1_router
from tax_assistant.config import Settings, get_settings
from tax_assistant.db import build_engine, init_db
from tax_assistant.models import TaxReturn
from tax_assistant.schemas import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(app_settings)
        init_db(engine)
        app.state.settings = app_settings
        app.state.engine = engine
        yield

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.include_router(v1_router, prefix="/v1")

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/app", include_in_schema=False)
    def app_shell() -> FileResponse:
        return FileResponse(static_dir / "index.html")

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
