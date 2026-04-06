from __future__ import annotations

from app.settings.config import Settings


DEMO_TOKEN_LOGIN_MESSAGE = "Sign in via TWC is unavailable for this demo. Use TWC Token."


class OAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return False

    def configuration_error(self) -> str | None:
        return DEMO_TOKEN_LOGIN_MESSAGE