# Created by: Raymond Reeves Engineering Tech 4 2026
from types import SimpleNamespace
from pathlib import Path
import unittest

from app.services.platform import PlatformService
from app.models.domain import BranchCacheSummary, WorkbenchAgentAdminSettings, WorkbenchAgentSecret
from app.services.three_ds_corpus import CorpusDocument


class WorkbenchAgentKnowledgeTests(unittest.TestCase):
    def test_workbench_admin_summary_access_does_not_require_self_grant(self) -> None:
        service = object.__new__(PlatformService)
        summary = BranchCacheSummary(server_id="twc-2024x", project_id="p1", branch_id="master", model_count=2)
        service._require_server = lambda *args, **kwargs: None
        service.repo = SimpleNamespace(get_branch_cache_summary=lambda *args: summary)

        allowed = service.get_branch_cache_summary_for_user(
            "twc-2024x",
            "admin",
            "p1",
            "master",
            include_all_workbench_admin=True,
        )

        self.assertEqual(allowed, summary)

    def test_agent_secret_falls_back_from_legacy_server_scope_to_user_global_scope(self) -> None:
        service = object.__new__(PlatformService)
        secret = WorkbenchAgentSecret(base_url="http://127.0.0.1:9172", api_key="secret", model_id="oss:20b")
        stored_payloads = {"workbench-agent:localhost:admin": secret.model_dump_json()}
        writes: list[tuple[str, str]] = []

        service.sessions = SimpleNamespace(cipher=SimpleNamespace(
            decrypt_raw=lambda value: value.encode("utf-8"),
            encrypt_raw=lambda value: value.decode("utf-8"),
        ))
        service.repo = SimpleNamespace(
            get_app_secret=lambda scope: (stored_payloads[scope], "now") if scope in stored_payloads else None,
            delete_app_secret=lambda scope: stored_payloads.pop(scope, None),
            list_app_secret_scopes=lambda prefix="": [scope for scope in stored_payloads if scope.startswith(prefix)],
            upsert_app_secret=lambda scope, payload: writes.append((scope, payload)) or "now",
        )
        session = SimpleNamespace(
            server=SimpleNamespace(id="twc-2024x"),
            user=SimpleNamespace(preferred_username="admin"),
        )

        resolved = service._workbench_agent_secret(session)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.model_id, "oss:20b")
        self.assertIn("workbench-agent:twc-2024x:admin", [scope for scope, _ in writes])
        self.assertIn("workbench-agent:global:admin", [scope for scope, _ in writes])

    def test_openwebui_origin_is_https_and_allowlist_scoped_by_default(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(
            openwebui_allow_insecure_http=False,
            openwebui_allowed_hosts=["owui.example"],
        )

        self.assertEqual(
            service._normalize_openwebui_base_url("https://owui.example/api/"),
            "https://owui.example",
        )
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            service._normalize_openwebui_base_url("http://owui.example")
        with self.assertRaisesRegex(ValueError, "not listed"):
            service._normalize_openwebui_base_url("https://other.example")
        with self.assertRaisesRegex(ValueError, "without credentials"):
            service._normalize_openwebui_base_url("https://user:secret@owui.example")

    def test_agent_admin_settings_can_disable_https_certificate_verification(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(
            openwebui_verify_tls=True,
            openwebui_allow_insecure_http=False,
            openwebui_ca_bundle_path=None,
            openwebui_allowed_hosts=["old.example"],
        )
        service.repo = SimpleNamespace(
            get_agent_admin_settings=lambda: WorkbenchAgentAdminSettings(
                openwebui_verify_tls=False,
                openwebui_allow_insecure_http=False,
                openwebui_allowed_hosts=[],
            )
        )

        self.assertEqual(service._normalize_openwebui_base_url("https://owui.local/api"), "https://owui.local")
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            service._normalize_openwebui_base_url("http://owui.local/api")
        self.assertFalse(service._openwebui_verify())

    def test_agent_admin_settings_can_explicitly_allow_plain_http_for_lab_hosts(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace()
        service.repo = SimpleNamespace(
            get_agent_admin_settings=lambda: WorkbenchAgentAdminSettings(
                openwebui_verify_tls=False,
                openwebui_allow_insecure_http=True,
                openwebui_allowed_hosts=[],
            )
        )

        self.assertEqual(service._normalize_openwebui_base_url("http://owui.local/api"), "http://owui.local")

    def test_reference_documents_use_validated_authoritative_control_rails(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace()
        corpus = SimpleNamespace(
            root=Path("C:/authoritative/3DS_KB"),
            validated=lambda: SimpleNamespace(certificate_sha256="a" * 64),
            control_documents=lambda: (
                CorpusDocument(relative_path="AGENTS.md", content="ONLY-AUTHORITATIVE-CONTROL"),
            ),
        )
        service._validate_three_ds_corpus = lambda: corpus
        service._three_ds_kb_status = lambda: {
            "reference_available": True,
            "reference_page_count": 163671,
            "reference_chunk_count": 163670,
        }
        service._workbench_agent_example_payload = lambda: {"example.py": "print('workbench')"}

        documents, stats, fingerprint = service._build_workbench_reference_documents()

        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0][0], "twc-workbench-operating-reference.md")
        combined = b"\n".join(content for _, content in documents).decode("utf-8")
        self.assertEqual(combined.count("ONLY-AUTHORITATIVE-CONTROL"), 1)
        self.assertNotIn("C:\\authoritative\\3DS_KB", combined)
        self.assertNotIn("Corpus root:", combined)
        self.assertEqual(stats["reference_chunk_count"], 163670)
        self.assertEqual(len(fingerprint), 64)

    def test_reference_documents_teach_workbench_api_endpoint_creation(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace()
        corpus = SimpleNamespace(
            root=Path("C:/authoritative/3DS_KB"),
            validated=lambda: SimpleNamespace(certificate_sha256="c" * 64),
            control_documents=lambda: (),
        )
        service._validate_three_ds_corpus = lambda: corpus
        service._three_ds_kb_status = lambda: {
            "reference_available": True,
            "reference_page_count": 10,
            "reference_chunk_count": 9,
        }
        service._workbench_agent_example_payload = lambda: {"36_workbench_owned_elements.py": "print('owned elements')"}

        documents, _, _ = service._build_workbench_reference_documents()
        operating_reference = documents[0][1].decode("utf-8")

        self.assertIn("Workbench API endpoint creation map", operating_reference)
        self.assertIn("backend/app/api/routes/workspace.py", operating_reference)
        self.assertIn("frontend/src/services/api.ts", operating_reference)
        self.assertIn("36_workbench_owned_elements.py", operating_reference)

    def test_query_context_contains_only_retrieved_authoritative_documents(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace()
        corpus = SimpleNamespace(
            root=Path("C:/authoritative/3DS_KB"),
            validated=lambda: SimpleNamespace(certificate_sha256="b" * 64),
            retrieve=lambda *_args, **_kwargs: (
                CorpusDocument(relative_path="CAMEO_JAVA_OPENAPI_2024xR3/Element.md", content="getOwnedElement"),
            ),
        )
        service._validate_three_ds_corpus = lambda: corpus

        context = service._three_ds_query_context("How do I read owned elements?")

        self.assertIn("CAMEO_JAVA_OPENAPI_2024xR3/Element.md", context)
        self.assertIn("getOwnedElement", context)
        self.assertNotIn("C:\\authoritative\\3DS_KB", context)
        self.assertNotIn("Corpus root:", context)


class WorkbenchAgentKnowledgeUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_reference_file_is_uploaded_and_reused_as_one_set(self) -> None:
        service = object.__new__(PlatformService)
        documents = [
            ("twc-workbench-operating-reference.md", b"operations"),
            ("twc-3ds-kb-control-rails.md", b"controls"),
        ]
        service._build_workbench_reference_documents = lambda: (
            documents,
            {"reference_page_count": 2, "reference_chunk_count": 2},
            "fingerprint",
        )
        uploads: list[tuple[str, bytes]] = []

        async def upload(_secret, name: str, content: bytes) -> str:
            uploads.append((name, content))
            return f"file-{len(uploads)}"

        service._upload_openwebui_markdown_file = upload
        secret = SimpleNamespace(
            reference_file_ids=[],
            reference_file_names=[],
            reference_file_id=None,
            reference_file_name=None,
            reference_fingerprint=None,
        )

        uploaded, stats, fingerprint = await service._ensure_workbench_reference_knowledge(secret)

        self.assertEqual(uploads, documents)
        self.assertEqual([file_id for file_id, _ in uploaded], ["file-1", "file-2"])
        self.assertEqual(stats["reference_chunk_count"], 2)
        self.assertEqual(fingerprint, "fingerprint")

        reused_secret = SimpleNamespace(
            reference_file_ids=[file_id for file_id, _ in uploaded],
            reference_file_names=[name for _, name in uploaded],
            reference_file_id=None,
            reference_file_name=None,
            reference_fingerprint=fingerprint,
        )
        uploads.clear()
        reused, _, _ = await service._ensure_workbench_reference_knowledge(reused_secret)
        self.assertEqual(reused, uploaded)
        self.assertEqual(uploads, [])

    async def test_failed_reference_upload_can_resume_from_processed_prefix(self) -> None:
        service = object.__new__(PlatformService)
        documents = [("operations.md", b"ops"), ("control-rails.md", b"controls")]
        service._build_workbench_reference_documents = lambda: (
            documents,
            {"reference_page_count": 2, "reference_chunk_count": 2},
            "current-fingerprint",
        )
        uploaded_names: list[str] = []

        async def upload(_secret, name: str, _content: bytes) -> str:
            uploaded_names.append(name)
            return f"new-{name}"

        persisted: list[WorkbenchAgentSecret] = []
        service._upload_openwebui_markdown_file = upload
        service._store_workbench_agent_secret = lambda _session, value: persisted.append(value)
        secret = WorkbenchAgentSecret(
            base_url="https://owui.example",
            api_key="secret",
            reference_file_id="existing-operations",
            reference_file_name="operations.md",
            reference_file_ids=["existing-operations"],
            reference_file_names=["operations.md"],
            reference_fingerprint="current-fingerprint",
        )

        completed, _, _ = await service._ensure_workbench_reference_knowledge(
            secret,
            session=SimpleNamespace(),
        )

        self.assertEqual(uploaded_names, ["control-rails.md"])
        self.assertEqual(completed[0], ("existing-operations", "operations.md"))
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[-1].reference_file_names, ["operations.md", "control-rails.md"])


if __name__ == "__main__":
    unittest.main()
