from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from app.services.three_ds_corpus import ThreeDsCorpus


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ThreeDsCorpusTests(unittest.TestCase):
    def build_corpus(self, root: Path) -> tuple[Path, str]:
        evidence_path = "CAMEO_JAVA_OPENAPI_2024xR3/PAGES/Element.md"
        evidence = b"# Element\n\ngetOwnedElement\n"
        validation = b"# VALIDATION\n\n- result: PASS\n"
        (root / Path(evidence_path)).parent.mkdir(parents=True)
        (root / Path(evidence_path)).write_bytes(evidence)
        (root / "00_VALIDATION.md").write_bytes(validation)
        manifest = (
            "# MACHINE MANIFEST\n\n"
            "| Relative path | Bytes | SHA-256 |\n"
            "|---|---:|---|\n"
            f"| `{evidence_path}` | {len(evidence)} | `{sha256(evidence)}` |\n"
        ).encode()
        (root / "00_MACHINE_MANIFEST.md").write_bytes(manifest)
        records = b"".join(
            (
                f"1\t00_MACHINE_MANIFEST.md\t{len(manifest)}\t{sha256(manifest)}\n".encode(),
                f"2\t00_VALIDATION.md\t{len(validation)}\t{sha256(validation)}\n".encode(),
                f"3\t{evidence_path}\t{len(evidence)}\t{sha256(evidence)}\n".encode(),
            )
        )
        certificate_sha256 = sha256(records)
        controller = f"""# 3DS KB SINGLE ENTRY

- required manifest SHA-256: `{sha256(manifest)}`
- listed evidence rows: `1`
- required `00_VALIDATION.md` SHA-256: `{sha256(validation)}`

3-record stream must equal:

```text
{certificate_sha256}
```
"""
        (root / "AGENTS.md").write_text(controller, encoding="utf-8")
        return root / Path(evidence_path), certificate_sha256

    def test_serial_gate_reproduces_controller_certificate_and_retrieves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, expected_certificate = self.build_corpus(root)
            corpus = ThreeDsCorpus(root)
            certificate = root.parent / f"{root.name}-certificate.tsv"
            try:
                result = corpus.validate(certificate)
                documents = corpus.retrieve("2024xR3 Element getOwnedElement")
            finally:
                certificate.unlink(missing_ok=True)

            self.assertEqual(result.certificate_sha256, expected_certificate)
            self.assertEqual(result.evidence_record_count, 3)
            self.assertEqual(documents[0].relative_path, "CAMEO_JAVA_OPENAPI_2024xR3/PAGES/Element.md")
            self.assertIn("getOwnedElement", documents[0].content)

    def test_changed_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_path, _ = self.build_corpus(root)
            evidence_path.write_text("# changed\n", encoding="utf-8")
            corpus = ThreeDsCorpus(root)

            with self.assertRaisesRegex(RuntimeError, "3DS_CORPUS_INTEGRITY_FAILURE"):
                corpus.validate(root.parent / f"{root.name}-certificate.tsv")


if __name__ == "__main__":
    unittest.main()
