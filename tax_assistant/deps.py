from __future__ import annotations

from typing import Generator

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session

from tax_assistant.config import Settings
from tax_assistant.models import ApprovalRole
from tax_assistant.services.auth_service import actor_from_bearer_token, actor_from_headers
from tax_assistant.schemas import ActorContext


def get_session(request: Request) -> Generator[Session, None, None]:
    engine = request.app.state.engine
    with Session(engine) as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_actor_context(
    request: Request,
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> ActorContext:
    settings: Settings = request.app.state.settings
    if settings.normalized_auth_mode == "bearer":
        return actor_from_bearer_token(authorization, settings)
    return actor_from_headers(x_user_id, x_role)


def get_authenticated_actor(
    request: Request,
    actor: ActorContext = Depends(get_actor_context),
) -> ActorContext:
    settings: Settings = request.app.state.settings
    if settings.require_actor_identity and actor.user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authenticated actor is required")
    return actor


def get_cpa_actor(actor: ActorContext = Depends(get_authenticated_actor)) -> ActorContext:
    if actor.role != ApprovalRole.CPA:
        raise HTTPException(status_code=403, detail="CPA role required")
    return actor
