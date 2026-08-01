from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
import asyncio
import base64
import unittest
from unittest.mock import patch

import httpx

from app.api.routes import auth, workspace
from app.auth.twc import build_twc_oidc_authorization_url, exchange_twc_auth_code
from app.core.storage import SqliteRepository
from app.models.domain import (
    BranchAccessRecord,
    BranchCacheSummary,
    ServerProfile,
    ServerProfileCreate,
    CachedElementRecord,
    CachedModelRecord,
    WorkbenchAuthSettingsUpdate,
    WorkbenchGroupCreateRequest,
    WorkbenchGroupUpdateRequest,
    WorkbenchProjectAccessAssignmentRequest,
    WorkbenchUserCreateRequest,
    WorkbenchUserRole,
    WorkbenchUserUpdateRequest,
)
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

    def test_workbench_user_management_mode_local_disables_twc_auth_paths(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.settings = Settings(workbench_user_management_mode="local")
            service.repo = SqliteRepository(Path(directory) / "workbench.db")

            settings = service.get_auth_settings()

            self.assertEqual(settings.user_management_mode, "local")
            self.assertTrue(settings.local_users_enabled)
            self.assertFalse(settings.twc_redirect_enabled)
            self.assertFalse(settings.twc_token_enabled)

    def test_workbench_user_management_mode_twc_disables_local_auth_path(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.settings = Settings(workbench_user_management_mode="twc")
            service.repo = SqliteRepository(Path(directory) / "workbench.db")

            settings = service.get_auth_settings()

            self.assertEqual(settings.user_management_mode, "twc")
            self.assertFalse(settings.local_users_enabled)
            self.assertTrue(settings.twc_redirect_enabled)
            self.assertTrue(settings.twc_token_enabled)

            with self.assertRaisesRegex(ValueError, "At least one TWC sign-in method"):
                service.update_auth_settings(
                    WorkbenchAuthSettingsUpdate(twc_redirect_enabled=False, twc_token_enabled=False)
                )

    def test_default_admin_bootstrap_creates_rotatable_local_admin(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.settings = Settings(
                workbench_default_admin_username="admin",
                workbench_default_admin_password="admin",
            )
            service.repo = SqliteRepository(Path(directory) / "workbench.db")
            service.sessions = SimpleNamespace(
                create_session=lambda server, user, authorization_context, token_bundle, capabilities: SimpleNamespace(
                    session_id="session",
                    server=server,
                    user=user,
                    authorization_context=authorization_context,
                    created_at=datetime.now().astimezone(),
                )
            )
            service._require_server = lambda server_id, include_disabled=False: ServerProfile(
                id=server_id,
                name="TWC",
                base_url="https://twc.example",
            )
            service._snapshot_capabilities = lambda server: SimpleNamespace(capabilities={})
            service._update_user_server_state = lambda *args, **kwargs: None

            service.login_with_workbench_password(
                auth.WorkbenchLocalLoginRequest(server_id="twc", username="admin", password="admin")
            )

            user = service.repo.get_workbench_user("admin")
            self.assertIsNotNone(user)
            self.assertEqual(user.role, WorkbenchUserRole.ADMIN)
            self.assertTrue(user.password_change_required)

    def test_default_admin_bootstrap_allows_setup_login_without_presets(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.settings = Settings()
            service.repo = SqliteRepository(Path(directory) / "workbench.db")
            service.sessions = SimpleNamespace(
                create_session=lambda server, user, authorization_context, token_bundle, capabilities: SimpleNamespace(
                    session_id="session",
                    server=server,
                    user=user,
                    authorization_context=authorization_context,
                    created_at=datetime.now().astimezone(),
                )
            )
            service._snapshot_capabilities = lambda server: SimpleNamespace(capabilities={})
            service._update_user_server_state = lambda *args, **kwargs: None

            session = service.login_with_workbench_password(
                auth.WorkbenchLocalLoginRequest(server_id="", username="admin", password="admin")
            )

            self.assertEqual(session.server.id, "workbench-setup")
            self.assertEqual(session.user.auth_source, "workbench-local")

    def test_group_managers_only_manage_groups_they_belong_to(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.repo = SqliteRepository(Path(directory) / "workbench.db")
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="admin",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.ADMIN,
                    enabled=True,
                )
            )
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="manager",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.GROUP_MANAGER,
                    enabled=True,
                )
            )
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="other",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.USER,
                    enabled=True,
                )
            )
            service.create_workbench_group(
                WorkbenchGroupCreateRequest(name="owned", users=["manager"])
            )
            service.create_workbench_group(
                WorkbenchGroupCreateRequest(name="outside", users=["other"])
            )
            manager_session = SimpleNamespace(
                user=SimpleNamespace(preferred_username="manager"),
                authorization_context=SimpleNamespace(
                    can_manage_server_presets=False,
                    can_manage_groups=True,
                ),
            )

            self.assertEqual(
                [group.name for group in service.list_workbench_groups(manager_session)],
                ["owned"],
            )

            updated = service.update_workbench_group(
                manager_session,
                "owned",
                WorkbenchGroupUpdateRequest(description="managed safely"),
            )

            self.assertEqual(updated.description, "managed safely")
            with self.assertRaisesRegex(PermissionError, "only manage groups"):
                service.update_workbench_group(
                    manager_session,
                    "outside",
                    WorkbenchGroupUpdateRequest(description="should be blocked"),
                )
            with self.assertRaisesRegex(PermissionError, "Only Workbench administrators"):
                service.delete_workbench_group(manager_session, "owned")

    def test_group_manager_claim_is_exact_and_not_admin(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = Settings()

        context = service._build_authorization_context(
            "twc-manager",
            current_user_context=SimpleNamespace(
                roles=["Group Manager"],
                role_ids=[],
                groups=[],
                permissions=[],
                permissions_included=False,
            ),
            upstream_roles=None,
            upstream_groups=None,
        )

        self.assertTrue(context.can_manage_groups)
        self.assertFalse(context.can_manage_server_presets)
        self.assertFalse(service._claims_grant_group_manager(["Project Group Managers"], []))

    def test_project_access_admin_can_assign_only_their_project_branch(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.repo = SqliteRepository(Path(directory) / "workbench.db")
            service.settings = Settings(data_dir=Path(directory) / "data")
            service.repo.upsert_branch_cache_summary(
                BranchCacheSummary(
                    server_id="twc",
                    project_id="project-a",
                    branch_id="master",
                    workspace_id="workspace-a",
                    project_name="Project A",
                    branch_name="master",
                    source_kind="cameo-plugin",
                )
            )
            service.repo.upsert_branch_cache_summary(
                BranchCacheSummary(
                    server_id="twc",
                    project_id="project-b",
                    branch_id="master",
                    workspace_id="workspace-b",
                    project_name="Project B",
                    branch_name="master",
                    source_kind="cameo-plugin",
                )
            )
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="project-admin",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.USER,
                    enabled=True,
                )
            )
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="target",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.USER,
                    enabled=True,
                )
            )
            service.repo.upsert_branch_access_records([
                BranchAccessRecord(
                    user_id="project-admin",
                    server_id="twc",
                    project_id="project-a",
                    branch_id="master",
                    workspace_id="workspace-a",
                    accessible=True,
                    editable=True,
                    admin_access=True,
                    payload={"access_admin_access": True, "branch_admin_access": True},
                )
            ])
            session = SimpleNamespace(
                user=SimpleNamespace(preferred_username="project-admin"),
                server=SimpleNamespace(id="twc"),
                authorization_context=SimpleNamespace(
                    can_manage_server_presets=False,
                    can_manage_groups=False,
                ),
            )

            result = service.assign_workbench_project_access(
                session,
                WorkbenchProjectAccessAssignmentRequest(
                    principal_type="user",
                    principal_name="target",
                    project_id="project-a",
                    branch_id="master",
                    accessible=True,
                    editable=True,
                    admin_access=False,
                ),
            )

            self.assertEqual(result.assigned_usernames, ["target"])
            with self.assertRaisesRegex(PermissionError, "cannot manage access rights"):
                service.assign_workbench_project_access(
                    session,
                    WorkbenchProjectAccessAssignmentRequest(
                        principal_type="user",
                        principal_name="target",
                        project_id="project-b",
                        branch_id="master",
                        accessible=True,
                    ),
                )

    def test_workbench_admin_can_assign_project_access_but_not_self_grant(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.repo = SqliteRepository(Path(directory) / "workbench.db")
            service.repo.upsert_branch_cache_summary(
                BranchCacheSummary(
                    server_id="twc",
                    project_id="project-a",
                    branch_id="master",
                    workspace_id="workspace-a",
                    project_name="Project A",
                    branch_name="master",
                    source_kind="cameo-plugin",
                )
            )
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="admin",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.ADMIN,
                    enabled=True,
                )
            )
            service.create_workbench_user(
                WorkbenchUserCreateRequest(
                    username="target",
                    password="long-safe-passphrase",
                    role=WorkbenchUserRole.USER,
                    enabled=True,
                )
            )
            session = SimpleNamespace(
                user=SimpleNamespace(preferred_username="admin"),
                server=SimpleNamespace(id="twc"),
                authorization_context=SimpleNamespace(
                    can_manage_server_presets=True,
                    can_manage_groups=True,
                ),
            )

            with self.assertRaisesRegex(PermissionError, "cannot assign or elevate their own project access"):
                service.assign_workbench_project_access(
                    session,
                    WorkbenchProjectAccessAssignmentRequest(
                        principal_type="user",
                        principal_name="admin",
                        project_id="project-a",
                        branch_id="master",
                        accessible=True,
                        editable=True,
                        admin_access=True,
                    ),
                )

            result = service.assign_workbench_project_access(
                session,
                WorkbenchProjectAccessAssignmentRequest(
                    principal_type="user",
                    principal_name="target",
                    project_id="project-a",
                    branch_id="master",
                    accessible=True,
                    editable=True,
                    admin_access=True,
                )
            )
            self.assertEqual(result.assigned_usernames, ["target"])

    def test_workbench_admin_has_cached_branch_access_without_twc_permission_record(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            service = object.__new__(PlatformService)
            service.repo = SqliteRepository(Path(directory) / "workbench.db")
            service.settings = Settings(data_dir=Path(directory) / "data")
            service.repo.upsert_branch_cache_summary(
                BranchCacheSummary(
                    server_id="twc",
                    project_id="water",
                    branch_id="master",
                    workspace_id="workspace-water",
                    project_name="WaterSupply",
                    branch_name="trunk",
                    source_kind="cameo-plugin",
                )
            )
            service.repo.upsert_cached_models(
                [
                    CachedModelRecord(
                        server_id="twc",
                        project_id="water",
                        branch_id="master",
                        model_id="model-water",
                        workspace_id="workspace-water",
                        name="Water Supply",
                        root_ids=["root-water"],
                        element_count=1,
                        source_user="cameo",
                    )
                ]
            )
            session = SimpleNamespace(
                user=SimpleNamespace(preferred_username="admin"),
                server=SimpleNamespace(id="twc"),
                authorization_context=SimpleNamespace(
                    can_manage_server_presets=True,
                    can_manage_groups=True,
                ),
            )

            summary = service.get_branch_cache_summary(session, "water", "master")
            access = service._branch_access_for_session(session, "water", "master")
            status = service.current_permission_status(session, "water", "master")
            manifest = service.get_branch_access_manifest_status(session, "water", "master")
            snapshot = service.get_branch_cache_snapshot(session, "water", "master")
            model = service.get_cached_branch_model(session, "water", "master", "model-water")

            self.assertEqual(summary.project_id, "water")
            self.assertIsNotNone(access)
            self.assertTrue(access.accessible)
            self.assertFalse(access.editable)
            self.assertTrue(status.branch_accessible)
            self.assertTrue(status.project_accessible)
            self.assertTrue(manifest.current_user_accessible)
            self.assertFalse(manifest.current_user_access_admin_access)
            self.assertEqual([view.model.model_id for view in snapshot.models], ["model-water"])
            self.assertIsNotNone(model)
            self.assertIsNone(model.permissions)

    def test_empty_env_preset_catalog_does_not_delete_app_managed_servers(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            database_path = Path(directory) / "workbench.db"
            repo = SqliteRepository(database_path)
            repo.upsert_server(ServerProfile(name="Managed", base_url="https://twc.example"))

            from app.services.platform import ApplicationContainer

            ApplicationContainer(Settings(database_path=database_path, twc_preset_servers=[]))

            self.assertEqual(len(SqliteRepository(database_path).list_servers(include_disabled=True)), 1)

    def test_admin_created_server_profile_can_use_explicit_plugin_key(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            database_path = Path(directory) / "workbench.db"
            from app.services.platform import ApplicationContainer

            container = ApplicationContainer(Settings(database_path=database_path, twc_preset_servers=[]))
            created = container.platform.create_server(
                ServerProfileCreate(
                    id="prod-2024x",
                    name="Production 2024x",
                    base_url="https://twc.example:8111",
                    version="2024x",
                    verify_tls=True,
                    enabled=True,
                )
            )

            self.assertEqual(created.id, "prod-2024x")
            self.assertEqual(SqliteRepository(database_path).get_server("prod-2024x").base_url, "https://twc.example:8111")
            with self.assertRaisesRegex(ValueError, "already exists"):
                container.platform.create_server(
                    ServerProfileCreate(
                        id="prod-2024x",
                        name="Duplicate",
                        base_url="https://duplicate.example",
                    )
                )

    def test_cached_element_tree_summary_reads_inner_cameo_payload(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            database_path = Path(directory) / "workbench.db"
            repo = SqliteRepository(database_path)
            repo.upsert_cached_elements(
                [
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="parent",
                        name="Parent",
                        item_type="Package",
                        path="Model/Parent",
                        child_count=1,
                        payload={
                            "owner_id": "model",
                            "qualified_name": "Model::Parent",
                            "metaclass": "Package",
                            "owned_element_ids": ["child"],
                            "applied_stereotype_ids": ["stereotype"],
                            "diagram_type": "Package Diagram",
                        },
                    )
                ]
            )

            summary = repo.get_cached_element_tree_summary("server", "project", "branch", "parent", model_id="model")

            self.assertEqual(summary["owner_id"], "model")
            self.assertEqual(summary["child_count"], 1)
            self.assertEqual(summary["owned_element_ids"], ["child"])
            self.assertEqual(summary["applied_stereotype_ids"], ["stereotype"])
            self.assertEqual(summary["diagram_type"], "Package Diagram")

    def test_cameo_tree_root_display_order_and_comment_body_labels(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            service = object.__new__(PlatformService)
            service.repo = repo
            model = CachedModelRecord(
                server_id="server",
                project_id="project",
                branch_id="branch",
                model_id="model",
                name="Model Distiller_Example",
                root_ids=["distiller", "power", "virtual", "imported", "aux", "start", "index", "comment"],
                element_count=8,
            )
            repo.upsert_cached_elements(
                [
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="distiller",
                        name="Model Distiller",
                        item_type="Model",
                        path="Distiller",
                        payload={"owner_id": "model", "metaclass": "Model"},
                    ),
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="power",
                        name="Model Power Station",
                        item_type="Model",
                        path="Power Station",
                        payload={"owner_id": "model", "metaclass": "Model"},
                    ),
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="virtual",
                        name="Package Virtual dependencies",
                        item_type="Package",
                        path="Virtual dependencies",
                        payload={"owner_id": "model", "metaclass": "Package"},
                    ),
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="imported",
                        name="Package Imported Packages",
                        item_type="Package",
                        path="Imported Packages",
                        payload={"owner_id": "model", "metaclass": "Package"},
                    ),
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="aux",
                        name="Package Auxiliary",
                        item_type="Package",
                        path="Auxiliary",
                        payload={"owner_id": "model", "metaclass": "Package"},
                    ),
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="start",
                        name="Diagram Start",
                        item_type="Diagram",
                        path="Start",
                        payload={"owner_id": "model", "metaclass": "Diagram"},
                    ),
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="index",
                        name="Diagram Index",
                        item_type="Diagram",
                        path="Index",
                        payload={"owner_id": "model", "metaclass": "Diagram"},
                    ),
                    CachedElementRecord(
                        server_id="server",
                        project_id="project",
                        branch_id="branch",
                        model_id="model",
                        element_id="comment",
                        name="Comment",
                        item_type="Comment",
                        path="Comment",
                        payload={
                            "owner_id": "model",
                            "metaclass": "Comment",
                            "attributes": {
                                "body": "<html><body><p><b>Interface Control Document (ICD) Tables</b></p></body></html>"
                            },
                        },
                    ),
                ]
            )

            nodes = service._tree_children_for_model_root("server", "project", "branch", model)

            self.assertEqual(
                [node.label for node in nodes],
                [
                    "Auxiliary",
                    "Imported Packages",
                    "Virtual dependencies",
                    "Distiller",
                    "Power Station",
                    "Index",
                    "Start",
                    "Interface Control Document (ICD) Tables",
                ],
            )

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
