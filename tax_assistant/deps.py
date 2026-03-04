from __future__ import annotations

from typing import Generator

from fastapi import Header, HTTPException, Request
from sqlmodel import Session

from tax_assistant.config import Settings
from tax_assistant.models import ApprovalRole
from tax_assistant.schemas import ActorContext


def get_session(request: Request) -> Generator[Session, None, None]:
    engine = request.app.state.engine
    with Session(engine) as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_actor_context(
    x_user_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> ActorContext:
    role_value = (x_role or ApprovalRole.TAXPAYER.value).lower()
    try:
        role = ApprovalRole(role_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role_value}'") from exc

    return ActorContext(user_id=x_user_id or "anonymous", role=role)
