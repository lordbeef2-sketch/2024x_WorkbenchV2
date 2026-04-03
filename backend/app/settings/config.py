from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TWC Workbench"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5173"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8000"])
    data_dir: Path = Path("./data")
    database_path: Path | None = None
    export_dir: Path | None = None
    session_secret: str = "replace-this-in-production-with-32-random-bytes"
    session_cookie_name: str = "twc_session"
    session_ttl_minutes: int = 480
    secure_cookies: bool = False
    csrf_header_name: str = "X-CSRF-Token"
    log_level: str = "INFO"
    enable_pat_login: bool = False
    pat_admin_secret: str | None = None
    redis_url: str | None = None
    publisher_mode: str = "local"
    publisher_command: str | None = None
    publisher_webhook_url: str | None = None
    root_path: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.resolve()

    @property
    def resolved_database_path(self) -> Path:
        return (self.database_path or self.resolved_data_dir / "twc_workbench.sqlite3").resolve()

    @property
    def resolved_export_dir(self) -> Path:
        return (self.export_dir or self.resolved_data_dir / "exports").resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_export_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
