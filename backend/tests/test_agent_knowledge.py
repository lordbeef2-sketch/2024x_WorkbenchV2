from types import SimpleNamespace
from pathlib import Path
import unittest

from app.services.platform import PlatformService
from app.models.domain import WorkbenchAgentSecret
from app.services.three_ds_corpus import CorpusDocument


class WorkbenchAgentKnowledgeTests(unittest.TestCase):
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
            "three_ds_kb_available": True,
            "three_ds_kb_page_count": 163671,
            "three_ds_kb_chunk_count": 163670,
        }
        service._workbench_agent_example_payload = lambda: {"example.py": "print('workbench')"}

        documents, stats, fingerprint = service._build_workbench_reference_documents()

        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0][0], "twc-workbench-operating-reference.md")
        combined = b"\n".join(content for _, content in documents).decode("utf-8")
        self.assertEqual(combined.count("ONLY-AUTHORITATIVE-CONTROL"), 1)
        self.assertIn("C:\\authoritative\\3DS_KB", combined)
        self.assertEqual(stats["three_ds_kb_chunk_count"], 163670)
        self.assertEqual(len(fingerprint), 64)

    def test_query_context_contains_only_retrieved_authoritative_documents(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(
            three_ds_kb_retrieval_max_documents=12,
            three_ds_kb_retrieval_max_characters=120_000,
        )
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
        self.assertIn("C:\\authoritative\\3DS_KB", context)


class WorkbenchAgentKnowledgeUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_reference_file_is_uploaded_and_reused_as_one_set(self) -> None:
        service = object.__new__(PlatformService)
        documents = [
            ("twc-workbench-operating-reference.md", b"operations"),
            ("twc-3ds-kb-control-rails.md", b"controls"),
        ]
        service._build_workbench_reference_documents = lambda: (
            documents,
            {"three_ds_kb_page_count": 2, "three_ds_kb_chunk_count": 2},
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
        self.assertEqual(stats["three_ds_kb_chunk_count"], 2)
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
            {"three_ds_kb_page_count": 2, "three_ds_kb_chunk_count": 2},
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
