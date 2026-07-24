from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from tempfile import TemporaryDirectory
import asyncio
import base64
import unittest
from unittest.mock import patch

import httpx

from app.api.routes import auth, workspace
from app.auth.twc import build_twc_oidc_authorization_url, exchange_twc_auth_code
from app.core.storage import SqliteRepository
from app.models.domain import ServerProfile, WorkbenchUserCreateRequest, WorkbenchUserRole, WorkbenchUserUpdateRequest
from app.services.platform import PlatformService
from app.settings.config import Settings


class AuthenticationSourceTruthTests(unittest.TestCase):
    def test_main_signin_uses_documented_client_code_and_redirect_fields(self) -> None:
        settings = Settings(
            app_origin="https://workbench.example",
            twc_auth_client_id="twcworkbench-twc-2024x",
            twc_auth_client_secret="test-secret",
            twc_oidc_authorize_url="https://twc.example:8443/authentication/oidc/authorize",
        )
        server = ServerProfile(
            id="twc-2024x",
            name="TWC 2024x",
            base_url="https://twc.example:8111",
        )

        url = build_twc_oidc_authorization_url(SimpleNamespace(settings=settings), server, "state-value")
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["client_id"], ["twcworkbench-twc-2024x"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["openid"])
        self.assertEqual(query["redirect_uri"], ["https://workbench.example/api/auth/callback"])
        self.assertEqual(query["state"], ["state-value"])
        self.assertNotIn("oauth_consumer_key", query)
        self.assertNotIn("oauth_token", query)
        self.assertEqual(urlparse(url).path, "/authentication/oidc/authorize")

    def test_2024x_oidc_defaults_use_refresh3_discovery_and_token_paths(self) -> None:
        settings = Settings()

        self.assertEqual(settings.twc_oidc_discovery_path, "/authentication/.well-known/oidc-configuration")
        self.assertEqual(settings.twc_oidc_authorize_path, "/authentication/oidc/authorize")
        self.assertEqual(settings.twc_oidc_token_path, "/authentication/api/oidc/token")
        self.assertEqual(settings.twc_oidc_token_auth_method, "client_secret_basic")
        self.assertEqual(settings.twc_auth_scope, "openid")

    def test_code_exchange_uses_discovered_oidc_endpoint_and_client_secret_basic(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeResponse:
            def __init__(self, payload):
                self.status_code = 200
                self._payload = payload
                self.text = ""

            def json(self):
                return self._payload

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, **kwargs):
                calls.append(("get", url))
                return FakeResponse(
                    {
                        "authorization_endpoint": "https://auth.example/authentication/oidc/authorize",
                        "token_endpoint": "https://auth.example/authentication/api/oidc/token",
                        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                        "scopes_supported": ["openid"],
                    }
                )

            async def post(self, url, **kwargs):
                calls.append(("post", {"url": url, **kwargs}))
                return FakeResponse({"id_token": "header.payload.signature", "refresh_token": "refresh"})

        settings = Settings(
            app_origin="https://workbench.example",
            twc_auth_client_id="client-id",
            twc_auth_client_secret="client-secret",
        )
        server = ServerProfile(
            id="twc-2024x",
            name="TWC 2024x",
            base_url="https://twc.example:8111",
        )
        container = SimpleNamespace(settings=settings)

        with patch("app.auth.twc.httpx.AsyncClient", FakeAsyncClient):
            bundle = asyncio.run(exchange_twc_auth_code(container, server, "code-value"))

        post = next(value for method, value in calls if method == "post")
        self.assertEqual(post["url"], "https://auth.example/authentication/api/oidc/token")
        request = next(post["auth"].auth_flow(httpx.Request("POST", post["url"])))
        expected = base64.b64encode(b"client-id:client-secret").decode("ascii")
        self.assertEqual(request.headers["Authorization"], f"Basic {expected}")
        self.assertEqual(post["data"]["scope"], "openid")
        self.assertEqual(bundle.access_token, "header.payload.signature")

    def test_oidc_callback_rejects_missing_state(self) -> None:
        settings = Settings(app_origin="https://workbench.example", session_secret="test-session-secret")
        container = SimpleNamespace(settings=settings)
        expected_state, cookie = auth.create_auth_state_cookie(container, "twc-2024x")
        self.assertTrue(expected_state)
        request = SimpleNamespace(
            cookies={
                settings.pending_server_cookie_name: "twc-2024x",
                settings.auth_state_cookie_name: cookie,
            },
            headers={},
        )

        response = asyncio.run(auth.callback(request, code="code-value", state=None, container=container))

        self.assertEqual(response.status_code, 302)
        self.assertIn("OIDC+state+is+missing", response.headers["location"])

    def test_auth_options_exposes_exact_redirect_uri(self) -> None:
        settings = Settings(app_origin="https://workbench.example")

        options = auth.get_auth_options(SimpleNamespace(settings=settings))

        self.assertEqual(options["redirect_uri"], "https://workbench.example/api/auth/callback")

    def test_workbench_local_users_cannot_remove_last_enabled_admin(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.repo = SqliteRepository(Path(directory) / "workbench.db")
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="admin",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.ADMIN,
                    enabled=True,
                    display_name="Admin",
                )
            )

            with self.assertRaisesRegex(ValueError, "At least one enabled Workbench admin"):
                service.update_workbench_user("admin", WorkbenchUserUpdateRequest(role=WorkbenchUserRole.USER))

            with self.assertRaisesRegex(ValueError, "At least one enabled Workbench admin"):
                service.delete_workbench_user("admin")

    def test_unsupported_oslc_authentication_routes_are_not_exposed(self) -> None:
        paths = {
            route.path
            for router in (auth.router, workspace.router)
            for route in router.routes
        }

        self.assertFalse(any("/oslc" in path.lower() for path in paths))

    def test_settings_do_not_accept_an_active_oslc_consumer_configuration(self) -> None:
        settings = Settings()

        self.assertFalse(hasattr(settings, "twc_oslc_consumer_key"))
        self.assertFalse(hasattr(settings, "twc_oslc_consumer_secret"))
        self.assertFalse(hasattr(settings, "twc_oslc_callback_path"))

    def test_settings_do_not_expose_legacy_saml_client_or_nonstandard_token_methods(self) -> None:
        settings = Settings()
        env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

        self.assertFalse(hasattr(settings, "twc_saml_authorize_url"))
        self.assertFalse(hasattr(settings, "twc_saml_token_url"))
        self.assertNotIn("TWC_SAML_", env_example)
        with self.assertRaises(ValueError):
            Settings(twc_oidc_token_auth_method="x_auth_secret")

    def test_rest_model_crawler_routes_are_not_exposed(self) -> None:
        paths = {route.path for route in workspace.router.routes}

        self.assertNotIn("/workspace/model-cache/sync", paths)
        self.assertNotIn("/workspace/fallback-cache/status", paths)
        self.assertNotIn("/workspace/fallback-cache/refresh", paths)

    def test_active_model_routes_do_not_invent_workspace_latest_model_paths(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for relative_path in (
            Path("backend/app/adapters/teamwork.py"),
            Path("examples/Modules/commands.py"),
        ):
            source = (root / relative_path).read_text(encoding="utf-8")
            self.assertNotIn(
                "/osmc/workspaces/{workspace_id}/resources/{project_id}/branches/{branch_id}/models",
                source,
                str(relative_path),
            )

    def test_cameo_agent_action_launches_grounded_workbench_tab(self) -> None:
        root = Path(__file__).resolve().parents[2]
        plugin_source = (
            root / "plugin/src/main/java/com/twcworkbench/cameo/TWCWorkbenchCameoPlugin.java"
        ).read_text(encoding="utf-8")
        plugin_tree = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (root / "plugin/src/main/java").rglob("*.java")
        )

        self.assertIn('/workspace?tab=agent', plugin_source)
        self.assertNotIn('/api/chat/completions', plugin_tree)
        self.assertNotIn('agentApiKey', plugin_tree)


if __name__ == "__main__":
    unittest.main()
