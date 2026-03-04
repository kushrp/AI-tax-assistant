from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Collaborative Tax Assistant"
    database_url: str = "sqlite:///./data/tax_assistant.db"
    storage_dir: str = "./data/uploads"
    retention_days: int = 90
    material_confidence_threshold: float = 0.8

    model_config = SettingsConfigDict(env_prefix="TAX_ASSISTANT_", env_file=".env", extra="ignore")

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir).resolve()

    @property
    def sqlite_file_path(self) -> Optional[Path]:
        if not self.database_url.startswith("sqlite:///"):
            return None
        raw_path = self.database_url.removeprefix("sqlite:///")
        if raw_path in {"", ":memory:"}:
            return None
        return Path(raw_path).expanduser().resolve()

    def ensure_paths(self) -> None:
        self.storage_path.mkdir(parents=True, exist_ok=True)
        sqlite_file_path = self.sqlite_file_path
        if sqlite_file_path:
            sqlite_file_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
