from types import SimpleNamespace
import unittest

from app.services.platform import PlatformService
from app.models.domain import WorkbenchAgentSecret


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

    def test_full_3ds_kb_is_split_without_dropping_chunks(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(three_ds_kb_reference_file_max_bytes=4_000)
        chunks = [
            {
                "chunk_id": f"chunk-{index}",
                "title": f"Reference {index}",
                "url": f"https://docs.example/{index}",
                "content": f"UNIQUE-CONTENT-{index} " + ("x" * 1_800),
            }
            for index in range(5)
        ]
        service._three_ds_kb_chunks = lambda: (
            chunks,
            {"three_ds_kb_page_count": 5, "three_ds_kb_chunk_count": 5},
        )
        service._workbench_agent_example_payload = lambda: {"example.py": "print('workbench')"}

        documents, stats, fingerprint = service._build_workbench_reference_documents()

        self.assertGreater(len(documents), 2)
        self.assertEqual(documents[0][0], "twc-workbench-operating-reference.md")
        combined = b"\n".join(content for _, content in documents).decode("utf-8")
        for index in range(5):
            self.assertEqual(combined.count(f"UNIQUE-CONTENT-{index}"), 1)
        self.assertEqual(stats["three_ds_kb_chunk_count"], 5)
        self.assertEqual(len(fingerprint), 64)


class WorkbenchAgentKnowledgeUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_segment_is_uploaded_and_reused_as_one_reference_set(self) -> None:
        service = object.__new__(PlatformService)
        documents = [
            ("twc-workbench-operating-reference.md", b"operations"),
            ("twc-3ds-2024x-reference-part-001.md", b"part one"),
            ("twc-3ds-2024x-reference-part-002.md", b"part two"),
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
        self.assertEqual([file_id for file_id, _ in uploaded], ["file-1", "file-2", "file-3"])
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

    async def test_failed_segment_can_resume_from_persisted_processed_prefix(self) -> None:
        service = object.__new__(PlatformService)
        documents = [("operations.md", b"ops"), ("part-1.md", b"one"), ("part-2.md", b"two")]
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

        self.assertEqual(uploaded_names, ["part-1.md", "part-2.md"])
        self.assertEqual(completed[0], ("existing-operations", "operations.md"))
        self.assertEqual(len(persisted), 2)
        self.assertEqual(persisted[-1].reference_file_names, ["operations.md", "part-1.md", "part-2.md"])


if __name__ == "__main__":
    unittest.main()
