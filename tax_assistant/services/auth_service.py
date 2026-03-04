from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException
import jwt
from jwt import PyJWKClient

from tax_assistant.config import Settings
from tax_assistant.models import ApprovalRole
from tax_assistant.schemas import ActorContext


def actor_from_headers(x_user_id: str | None, x_role: str | None) -> ActorContext:
    role_value = (x_role or ApprovalRole.TAXPAYER.value).lower()
    role = _parse_role(role_value, error_status=400)
    return ActorContext(user_id=(x_user_id or "anonymous").strip() or "anonymous", role=role)


def actor_from_bearer_token(authorization: str | None, settings: Settings) -> ActorContext:
    token = _extract_bearer_token(authorization)
    if token is None:
        return ActorContext(user_id="anonymous", role=ApprovalRole.TAXPAYER)

    payload = _decode_token(token, settings)
    user_claim = settings.auth_user_id_claim.strip() or "sub"
    user_id = str(payload.get(user_claim, "")).strip()
    if not user_id:
        raise HTTPException(status_code=401, detail=f"Token missing required claim '{user_claim}'")

    role_claim = settings.auth_role_claim.strip() or "role"
    role = _parse_role(payload.get(role_claim), error_status=403)
    return ActorContext(user_id=user_id, role=role)


def _extract_bearer_token(authorization: str | None) -> str | None:
    raw = (authorization or "").strip()
    if not raw:
        return None
    parts = raw.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is missing")
    return token


def _decode_token(token: str, settings: Settings) -> dict:
    try:
        decode_kwargs: dict = {
            "algorithms": settings.parsed_auth_algorithms,
        }
        if settings.auth_audience:
            decode_kwargs["audience"] = settings.auth_audience
        else:
            decode_kwargs["options"] = {"verify_aud": False}
        if settings.auth_issuer:
            decode_kwargs["issuer"] = settings.auth_issuer

        if settings.auth_jwt_secret:
            return jwt.decode(token, settings.auth_jwt_secret, **decode_kwargs)

        jwks_url = (settings.auth_jwks_url or "").strip()
        if not jwks_url:
            raise HTTPException(
                status_code=500,
                detail="Bearer auth is enabled but no token verifier is configured",
            )
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        return jwt.decode(token, signing_key, **decode_kwargs)
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid bearer token: {exc}") from exc


def _parse_role(raw_role: object, *, error_status: int) -> ApprovalRole:
    if isinstance(raw_role, list):
        for item in raw_role:
            parsed = _maybe_role(item)
            if parsed:
                return parsed
        raise HTTPException(status_code=error_status, detail="Token does not include an allowed role")

    parsed = _maybe_role(raw_role)
    if parsed:
        return parsed
    raise HTTPException(status_code=error_status, detail=f"Invalid role '{raw_role}'")


def _maybe_role(raw_role: object) -> ApprovalRole | None:
    if raw_role is None:
        return ApprovalRole.TAXPAYER
    if isinstance(raw_role, ApprovalRole):
        return raw_role
    value = str(raw_role).strip().lower()
    if not value:
        return ApprovalRole.TAXPAYER
    try:
        return ApprovalRole(value)
    except ValueError:
        return None


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)
