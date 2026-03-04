from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Collaborative Tax Assistant"
    database_url: str = "sqlite:///./data/tax_assistant.db"
    storage_dir: str = "./data/uploads"
    storage_backend: str = "local"
    storage_bucket: str = ""
    storage_prefix: str = "tax-assistant"
    storage_endpoint_url: Optional[str] = None
    storage_region: Optional[str] = None
    storage_access_key_id: Optional[str] = None
    storage_secret_access_key: Optional[str] = None
    api_base_url: str = ""
    cors_allowed_origins: str = ""
    retention_days: int = 90
    material_confidence_threshold: float = 0.8
    require_actor_identity: bool = True
    auth_mode: str = "header"
    auth_jwks_url: Optional[str] = None
    auth_jwt_secret: Optional[str] = None
    auth_issuer: Optional[str] = None
    auth_audience: Optional[str] = None
    auth_role_claim: str = "role"
    auth_user_id_claim: str = "sub"
    auth_allowed_algorithms: str = "RS256,HS256"

    model_config = SettingsConfigDict(env_prefix="TAX_ASSISTANT_", env_file=".env", extra="ignore")

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir).resolve()

    @property
    def normalized_storage_backend(self) -> str:
        return self.storage_backend.strip().lower() or "local"

    @property
    def parsed_cors_allowed_origins(self) -> list[str]:
        raw = self.cors_allowed_origins.strip()
        if not raw:
            return []
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def normalized_auth_mode(self) -> str:
        mode = self.auth_mode.strip().lower() or "header"
        if mode not in {"header", "bearer"}:
            raise ValueError("TAX_ASSISTANT_AUTH_MODE must be 'header' or 'bearer'")
        return mode

    @property
    def parsed_auth_algorithms(self) -> list[str]:
        raw = self.auth_allowed_algorithms.strip()
        if not raw:
            return ["RS256", "HS256"]
        algorithms = [item.strip().upper() for item in raw.split(",") if item.strip()]
        return algorithms or ["RS256", "HS256"]

    @property
    def normalized_api_base_url(self) -> str:
        raw = self.api_base_url.strip()
        return raw.rstrip("/")

    @property
    def sqlite_file_path(self) -> Optional[Path]:
        if not self.database_url.startswith("sqlite:///"):
            return None
        raw_path = self.database_url.removeprefix("sqlite:///")
        if raw_path in {"", ":memory:"}:
            return None
        return Path(raw_path).expanduser().resolve()

    def ensure_paths(self) -> None:
        if self.normalized_storage_backend == "local":
            self.storage_path.mkdir(parents=True, exist_ok=True)
        sqlite_file_path = self.sqlite_file_path
        if sqlite_file_path:
            sqlite_file_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
