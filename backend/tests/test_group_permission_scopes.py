from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from app.adapters.teamwork import TeamworkAdapter
from app.models.domain import (
    AuthorizationContext,
    AuthorizationPermissionClaim,
    BranchAccessRecord,
    BranchCacheSummary,
    BranchPermissionAttachment,
    CachedModelRecord,
    ModelPermissionSnapshot,
    PermissionManifest,
    PermissionManifestEntry,
    ServerPermissionInventory,
)
from app.services.platform import PlatformService


class GroupPermissionScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_group_is_checked_for_global_and_project_scopes(self) -> None:
        adapter = object.__new__(TeamworkAdapter)
        adapter.context = SimpleNamespace(server=SimpleNamespace(id="server"))
        roles = [
            {
                "ID": "reviewer-role",
                "name": "Resource Reviewer",
                "permissions": [{"name": "Read Resources"}],
            },
            {
                "ID": "manager-role",
                "name": "Resource Manager",
                "permissions": [
                    {"name": "Read Resources"},
                    {"name": "Edit Resources"},
                    {"name": "Edit Resource Properties"},
                    {"name": "Administer Resources"},
                    {"name": "Manage Owned Resource Access Right"},
                ],
            },
        ]
        groups = [
            {
                "ID": "global-admins",
                "name": "Global Resource Admins",
                "nestedGroups": [{"ID": "admin-members"}],
                "roleAssignments": [{"roleID": "manager-role", "protectedObjects": []}],
            },
            {
                "ID": "admin-members",
                "name": "Admin Members",
                "usernames": ["Administrator"],
                "roleAssignments": [],
            },
            {
                "ID": "project-a-reviewers",
                "name": "Project A Reviewers",
                "usernames": ["ScopedReviewer"],
                "roleAssignments": [
                    {"roleID": "reviewer-role", "protectedObjects": [{"ID": "project-a"}]}
                ],
            },
            {
                "ID": "project-b-reviewers",
                "name": "Project B Reviewers",
                "usernames": ["WrongProjectUser"],
                "roleAssignments": [
                    {
                        "roleID": "reviewer-role",
                        "protectedObjects": [{"ID": "project-b", "containerId": "workspace-a"}],
                    }
                ],
            },
        ]
        adapter._project_roles = AsyncMock(return_value=roles)
        adapter._admin_roles = AsyncMock(return_value=[])
        adapter._admin_usergroups = AsyncMock(return_value=groups)
        adapter._project_role_users = AsyncMock(return_value=[])
        adapter._project_role_usergroups = AsyncMock(return_value=[])
        adapter._user_readonly_branches = AsyncMock(return_value=[])
        adapter._admin_usergroup = AsyncMock(return_value=None)

        records = await adapter.build_plugin_branch_access_manifest(
            "project-a",
            "main",
            workspace_id="workspace-a",
        )

        records_by_user = {record.user_id: record for record in records}
        self.assertEqual(set(records_by_user), {"administrator", "scopedreviewer"})
        self.assertTrue(records_by_user["administrator"].accessible)
        self.assertTrue(records_by_user["administrator"].editable)
        self.assertTrue(records_by_user["administrator"].admin_access)
        self.assertEqual(records_by_user["administrator"].via_groups, ["Global Resource Admins"])
        self.assertTrue(records_by_user["scopedreviewer"].accessible)
        self.assertFalse(records_by_user["scopedreviewer"].editable)

    def test_server_admin_global_scope_does_not_imply_project_read(self) -> None:
        adapter = object.__new__(TeamworkAdapter)
        role = {
            "ID": "server-admin-role",
            "name": "Server Administrator",
            "permissions": [{"name": "Configure Server"}],
        }

        self.assertEqual(adapter._role_access_flags(role), (False, False, False, False))
        self.assertTrue(
            adapter._role_assignment_applies_to_project(
                {"roleID": "server-admin-role", "protectedObjects": []},
                "project-a",
                "workspace-a",
            )
        )

    def test_workspace_protected_object_applies_category_role_to_project(self) -> None:
        adapter = object.__new__(TeamworkAdapter)

        self.assertTrue(
            adapter._role_assignment_applies_to_project(
                {
                    "roleID": "reviewer-role",
                    "protectedObjects": [{"ID": "workspace-a"}],
                },
                "project-a",
                "workspace-a",
            )
        )
        self.assertFalse(
            adapter._role_assignment_applies_to_project(
                {
                    "roleID": "reviewer-role",
                    "protectedObjects": [{"ID": "workspace-b"}],
                },
                "project-a",
                "workspace-a",
            )
        )

    def test_realswagger_permission_operation_names_are_authoritative(self) -> None:
        adapter = object.__new__(TeamworkAdapter)
        role = {
            "ID": "custom-role",
            "name": "Localized custom role",
            "permissions": [
                {
                    "name": "com.nomagic.esi.resource_read.resource",
                    "operationName": "read.resource",
                    "operationDisplayName": "Read Projects",
                },
                {
                    "name": "com.nomagic.esi.resource_edit.resource",
                    "operationName": "edit.resource",
                    "operationDisplayName": "Edit Projects",
                },
            ],
        }

        self.assertEqual(adapter._role_access_flags(role), (True, True, False, False))

    def test_expanded_security_manager_permissions_grant_documented_resource_access(self) -> None:
        adapter = object.__new__(TeamworkAdapter)
        role = {
            "ID": "security-manager-role",
            "name": "Security Manager",
            "permissions": [
                {"name": "List All Resources"},
                {"name": "Manage User Permissions"},
                {"name": "Manage Security Roles"},
            ],
        }

        self.assertEqual(adapter._role_access_flags(role), (True, False, False, True))

    async def test_fresh_effective_group_permissions_can_prove_access_when_branch_probe_is_restricted(self) -> None:
        service = object.__new__(PlatformService)
        summary = BranchCacheSummary(
            server_id="server",
            project_id="project-a",
            branch_id="main",
            model_count=1,
        )
        model = CachedModelRecord(
            server_id="server",
            project_id="project-a",
            branch_id="main",
            model_id="model-1",
            name="Model",
        )
        manifest_access = BranchAccessRecord(
            user_id="administrator",
            server_id="server",
            project_id="project-a",
            branch_id="main",
            accessible=True,
            editable=True,
            admin_access=True,
            roles=["Resource Manager"],
            via_groups=["Global Resource Admins"],
            payload={"branch_admin_access": True, "access_admin_access": True},
        )
        denied_probe = ModelPermissionSnapshot(
            user_id="administrator",
            server_id="server",
            project_id="project-a",
            branch_id="main",
            model_id="model-1",
            accessible=False,
            restricted=True,
            editable=False,
        )
        adapter = SimpleNamespace(
            build_plugin_branch_access_manifest=AsyncMock(return_value=[manifest_access]),
            probe_plugin_branch_permissions=AsyncMock(return_value=[denied_probe]),
        )
        service.repo = SimpleNamespace(
            list_cached_models=lambda *args: [model],
            get_branch_permission_attachment=lambda *args: None,
        )
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Administrator"),
            authorization_context=AuthorizationContext(
                roles=["Server Administrator", "Resource Manager"],
                groups=["Global Resource Admins"],
                permissions=[
                    AuthorizationPermissionClaim(name="Read Resources"),
                    AuthorizationPermissionClaim(name="Edit Resources"),
                    AuthorizationPermissionClaim(name="Edit Resource Properties"),
                    AuthorizationPermissionClaim(name="Administer Resources"),
                    AuthorizationPermissionClaim(name="Manage Owned Resource Access Right"),
                ],
            ),
        )

        branch_access, model_permissions, _ = await service._resolve_user_branch_permission_snapshot(
            session,
            summary,
            adapter=adapter,
            refreshed_at=model.synced_at,
        )

        self.assertTrue(branch_access.accessible)
        self.assertTrue(branch_access.editable)
        self.assertTrue(branch_access.admin_access)
        self.assertEqual(branch_access.via_groups, ["Global Resource Admins"])
        self.assertTrue(model_permissions[0].accessible)
        self.assertFalse(model_permissions[0].restricted)
        adapter.build_plugin_branch_access_manifest.assert_not_awaited()

    def test_current_user_global_resource_permissions_apply_to_every_project(self) -> None:
        adapter = object.__new__(TeamworkAdapter)
        current_user = adapter._extract_current_user_context(
            {
                "userName": "Administrator",
                "roleAssignments": [{"roleID": "resource-manager-role"}],
                "permissions": [
                    {"permissionInfo": {"name": "Read Resources"}, "relatedResources": []},
                    {"permissionInfo": {"name": "Edit Resources"}, "relatedResources": []},
                    {"permissionInfo": {"name": "Edit Resource Properties"}, "relatedResources": []},
                    {"permissionInfo": {"name": "Administer Resources"}, "relatedResources": []},
                ],
            }
        )
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=AuthorizationContext(permissions=current_user.permissions),
        )

        flags = service._session_resource_permission_flags(session, "project-a", "workspace-a")

        self.assertEqual(current_user.preferred_username, "Administrator")
        self.assertTrue(current_user.permissions_included)
        self.assertEqual(current_user.role_ids, ["resource-manager-role"])
        self.assertEqual(len(current_user.permissions), 4)
        self.assertTrue(flags["accessible"])
        self.assertTrue(flags["editable"])
        self.assertTrue(flags["branch_admin_access"])

    def test_scoped_current_user_permissions_do_not_leak_to_another_project(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=AuthorizationContext(
                permissions_included=True,
                permissions=[
                    AuthorizationPermissionClaim(
                        name="Read Resources",
                        related_resources=["project-b"],
                    )
                ]
            )
        )

        flags = service._session_resource_permission_flags(session, "project-a", "workspace-a")

        self.assertFalse(flags["accessible"])

    def test_canonical_rest_permission_operations_map_to_project_access(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=AuthorizationContext(
                permissions_included=True,
                permissions=[
                    AuthorizationPermissionClaim(
                        name="com.nomagic.esi.resource_read.resource",
                        operation_name="read.resource",
                        related_resources=["project-a"],
                    ),
                    AuthorizationPermissionClaim(
                        name="com.nomagic.esi.resource_edit.resource",
                        operation_name="edit.resource",
                        related_resources=["project-a"],
                    ),
                    AuthorizationPermissionClaim(name="Edit Resource Properties", related_resources=["project-a"]),
                    AuthorizationPermissionClaim(
                        name="Administer Resources",
                        related_resources=["project-a"],
                    ),
                ],
            )
        )

        flags = service._session_resource_permission_flags(session, "project-a", "workspace-a")

        self.assertTrue(flags["accessible"])
        self.assertTrue(flags["editable"])
        self.assertTrue(flags["branch_admin_access"])

    def test_list_all_resources_grants_read_access_without_granting_edit(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=AuthorizationContext(
                permissions_included=True,
                permissions=[
                    AuthorizationPermissionClaim(name="List All Resources", related_resources=[]),
                ],
            )
        )

        flags = service._session_resource_permission_flags(session, "project-a", "workspace-a")

        self.assertTrue(flags["accessible"])
        self.assertFalse(flags["editable"])
        self.assertFalse(flags["branch_admin_access"])

    def test_uuid_only_user_roles_are_resolved_from_shared_inventory(self) -> None:
        service = object.__new__(PlatformService)
        updated_sessions = []
        service.sessions = SimpleNamespace(
            update_authorization_context=lambda session, context: updated_sessions.append(context) or SimpleNamespace(
                authorization_context=context,
            )
        )
        session = SimpleNamespace(
            authorization_context=AuthorizationContext(
                role_ids=["resource-manager-role"],
                roles=[],
            )
        )
        inventory = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "resource-manager-role", "name": "Resource Manager"}],
        )

        updated = service._attach_inventory_role_names(session, inventory)

        self.assertEqual(updated.authorization_context.roles, ["Resource Manager"])
        self.assertEqual(updated_sessions[0].role_ids, ["resource-manager-role"])

    def test_refresh_candidates_include_every_imported_project_for_manifest_matching(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=AuthorizationContext(
                permissions_included=True,
                permissions=[
                    AuthorizationPermissionClaim(
                        name="Read Resources",
                        related_resources=["project-a"],
                    )
                ]
            )
        )
        summaries = [
            BranchCacheSummary(server_id="server", project_id="project-a", branch_id="main", source_kind="cameo-plugin"),
            BranchCacheSummary(server_id="server", project_id="project-b", branch_id="main", source_kind="cameo-plugin"),
            BranchCacheSummary(server_id="server", project_id="project-a", branch_id="legacy-rest", source_kind="twc-rest"),
        ]

        candidates = service._permission_candidate_summaries(session, summaries)

        self.assertEqual(
            [(item.project_id, item.branch_id) for item in candidates],
            [("project-a", "main"), ("project-b", "main")],
        )

    def test_refresh_with_explicit_empty_permissions_still_checks_imported_projects(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=AuthorizationContext(
                permissions_included=True,
                permissions=[],
            )
        )
        summaries = [BranchCacheSummary(server_id="server", project_id="project-a", branch_id="main", source_kind="cameo-plugin")]

        self.assertEqual(service._permission_candidate_summaries(session, summaries), summaries)

    async def test_saved_group_role_manifest_grants_access_when_current_user_permissions_are_empty(self) -> None:
        captured_at = CachedModelRecord(
            server_id="server",
            project_id="project-a",
            branch_id="main",
            model_id="model-1",
        ).synced_at
        summary = BranchCacheSummary(
            server_id="server",
            project_id="project-a",
            branch_id="main",
            latest_revision="42",
            source_kind="cameo-plugin",
        )
        model = CachedModelRecord(
            server_id="server",
            project_id="project-a",
            branch_id="main",
            model_id="model-1",
        )
        attachment = BranchPermissionAttachment(
            server_id="server",
            project_id="project-a",
            branch_id="main",
            latest_revision="42",
            attached_at=captured_at,
            manifest=PermissionManifest(
                source="twc-rest-role-manifest",
                complete=True,
                entries=[
                    PermissionManifestEntry(
                        scope_id="main",
                        scope_type="project-branch",
                        principal_name="alice",
                        principal_type="user",
                        role_name="Resource Manager",
                        accessible=True,
                        editable=True,
                        branch_admin_access=True,
                        via_groups=["Engineering"],
                    )
                ],
            ),
        )
        inventory = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "resource-manager"}],
            groups=[{"ID": "engineering"}],
            captured_at=captured_at,
        )
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service.repo = SimpleNamespace(
            list_cached_models=lambda *args: [model],
            get_branch_permission_attachment=lambda *args: attachment,
        )
        adapter = SimpleNamespace(probe_plugin_branch_permissions=AsyncMock())
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
            authorization_context=AuthorizationContext(
                permissions_included=True,
                permissions=[],
                roles=[],
                groups=[],
            ),
        )

        branch, permissions, _ = await service._resolve_user_branch_permission_snapshot(
            session,
            summary,
            adapter=adapter,
            permission_inventory=inventory,
            refreshed_at=captured_at,
        )

        self.assertTrue(branch.accessible)
        self.assertTrue(branch.editable)
        self.assertTrue(branch.admin_access)
        self.assertEqual(branch.roles, ["Resource Manager"])
        self.assertEqual(branch.via_groups, ["Engineering"])
        self.assertTrue(permissions[0].accessible)
        self.assertTrue(permissions[0].editable)
        adapter.probe_plugin_branch_permissions.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
