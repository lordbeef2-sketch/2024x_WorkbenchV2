from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    upstream_auth_cookie_names: list[str] = Field(default_factory=list)
    upstream_user_headers: list[str] = Field(
        default_factory=lambda: [
            "X-Forwarded-User",
            "Remote-User",
            "X-MS-CLIENT-PRINCIPAL-NAME",
            "X-Authenticated-User",
        ]
    )
    upstream_access_token_headers: list[str] = Field(
        default_factory=lambda: [
            "X-Forwarded-Access-Token",
            "X-Access-Token",
            "Authorization",
        ]
    )
    log_level: str = "INFO"
    redis_url: str | None = None
    publisher_mode: str = "local"
    publisher_command: str | None = None
    publisher_webhook_url: str | None = None
    root_path: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_path", "export_dir", mode="before")
    @classmethod
    def blank_paths_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.resolve()

    @property
    def resolved_database_path(self) -> Path:
        return (self.database_path or self.resolved_data_dir / "twc_workbench.sqlite3").resolve()

    @property
    def resolved_export_dir(self) -> Path:
        return (self.export_dir or self.resolved_data_dir / "exports").resolve()

    def extract_upstream_auth_cookies(self, cookies: Mapping[str, str]) -> dict[str, str]:
        allowed = {name.strip() for name in self.upstream_auth_cookie_names if name.strip()}
        if allowed:
            return {name: value for name, value in cookies.items() if name in allowed}
        return {name: value for name, value in cookies.items() if name != self.session_cookie_name}

    def extract_upstream_username(self, headers: Mapping[str, str]) -> str | None:
        for header_name in self.upstream_user_headers:
            value = headers.get(header_name)
            if value:
                return value.strip()
        return None

    def extract_upstream_access_token(self, headers: Mapping[str, str]) -> str | None:
        for header_name in self.upstream_access_token_headers:
            value = headers.get(header_name)
            if not value:
                continue
            token = value.strip()
            if not token:
                continue
            if header_name.lower() == "authorization":
                lower_token = token.lower()
                if lower_token.startswith("token "):
                    token = token[6:].strip()
                elif lower_token.startswith("bearer "):
                    token = token[7:].strip()
            return token or None
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_export_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
