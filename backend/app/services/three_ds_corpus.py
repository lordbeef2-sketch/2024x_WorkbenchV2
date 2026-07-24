from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


CONTROLLER_NAME = "AGENTS.md"
MANIFEST_NAME = "00_MACHINE_MANIFEST.md"
VALIDATION_NAME = "00_VALIDATION.md"

_MANIFEST_ROW = re.compile(
    r"^\| `(?P<path>.+)` \| (?P<bytes>\d+) \| `(?P<sha256>[0-9a-f]{64})` \|$"
)
_WORD = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class CorpusAnchors:
    manifest_sha256: str
    validation_sha256: str
    evidence_records: int
    certificate_records: int
    certificate_sha256: str


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    ordinal: int
    relative_path: str
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CorpusValidation:
    root: Path
    document_count: int
    evidence_record_count: int
    certificate_sha256: str
    certificate_path: Path


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    relative_path: str
    content: str
    truncated: bool = False


class ThreeDsCorpus:
    """Integrity gate and path-routed retrieval for the single 3DS KB."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self._anchors: CorpusAnchors | None = None
        self._entries: tuple[CorpusEntry, ...] | None = None
        self._validation: CorpusValidation | None = None

    @staticmethod
    def _sha256_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _parse_markdown(value: bytes, relative_path: str) -> str:
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"3DS_CORPUS_INTEGRITY_FAILURE: non-UTF-8 Markdown: {relative_path}") from exc
        if "\x00" in text:
            raise RuntimeError(f"3DS_CORPUS_INTEGRITY_FAILURE: NUL byte in Markdown: {relative_path}")
        # Consume every decoded line. This is the structural parse required by
        # the corpus gate; retrieval retains the original Markdown verbatim.
        for _ in text.splitlines():
            pass
        return text

    def _read_controller(self) -> tuple[bytes, CorpusAnchors]:
        controller_path = self.root / CONTROLLER_NAME
        try:
            controller_bytes = controller_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(
                f"3DS_CORPUS_INTEGRITY_FAILURE: controller was not readable: {controller_path}"
            ) from exc
        controller = self._parse_markdown(controller_bytes, CONTROLLER_NAME)

        def required(pattern: str, label: str) -> str:
            match = re.search(pattern, controller)
            if match is None:
                raise RuntimeError(f"3DS_CORPUS_INTEGRITY_FAILURE: controller omitted {label}")
            return match.group(1).lower()

        anchors = CorpusAnchors(
            manifest_sha256=required(r"required manifest SHA-256:\s*`([0-9a-fA-F]{64})`", "manifest hash"),
            validation_sha256=required(
                r"required `00_VALIDATION\.md` SHA-256:\s*`([0-9a-fA-F]{64})`",
                "validation hash",
            ),
            evidence_records=int(required(r"listed evidence rows:\s*`(\d+)`", "evidence row count")),
            certificate_records=int(
                required(r"(\d+)-record stream must equal:\s*```text", "certificate record count")
            ),
            certificate_sha256=required(
                r"\d+-record stream must equal:\s*```text\s*([0-9a-fA-F]{64})",
                "certificate hash",
            ),
        )
        if anchors.certificate_records != anchors.evidence_records + 2:
            raise RuntimeError(
                "3DS_CORPUS_INTEGRITY_FAILURE: certificate record count did not equal evidence rows plus controls"
            )
        return controller_bytes, anchors

    def _read_manifest_entries(self, manifest_bytes: bytes) -> tuple[CorpusEntry, ...]:
        manifest_text = self._parse_markdown(manifest_bytes, MANIFEST_NAME)
        entries: list[CorpusEntry] = []
        for line in manifest_text.splitlines():
            match = _MANIFEST_ROW.match(line)
            if match is None:
                continue
            relative_path = match.group("path").replace("\\", "/")
            candidate = (self.root / Path(relative_path)).resolve()
            if not candidate.is_relative_to(self.root):
                raise RuntimeError(
                    f"3DS_CORPUS_INTEGRITY_FAILURE: manifest path escaped corpus root: {relative_path}"
                )
            entries.append(
                CorpusEntry(
                    ordinal=len(entries) + 3,
                    relative_path=relative_path,
                    byte_count=int(match.group("bytes")),
                    sha256=match.group("sha256"),
                )
            )
        return tuple(entries)

    def inspect(self) -> tuple[CorpusAnchors, tuple[CorpusEntry, ...]]:
        if self._anchors is not None and self._entries is not None:
            return self._anchors, self._entries
        _, anchors = self._read_controller()
        manifest_path = self.root / MANIFEST_NAME
        validation_path = self.root / VALIDATION_NAME
        try:
            manifest_bytes = manifest_path.read_bytes()
            validation_bytes = validation_path.read_bytes()
        except OSError as exc:
            raise RuntimeError("3DS_CORPUS_INTEGRITY_FAILURE: manifest controls were not readable") from exc
        if self._sha256_bytes(manifest_bytes) != anchors.manifest_sha256:
            raise RuntimeError("3DS_CORPUS_INTEGRITY_FAILURE: manifest SHA-256 did not match AGENTS.md")
        if self._sha256_bytes(validation_bytes) != anchors.validation_sha256:
            raise RuntimeError("3DS_CORPUS_INTEGRITY_FAILURE: validation SHA-256 did not match AGENTS.md")
        self._parse_markdown(validation_bytes, VALIDATION_NAME)
        entries = self._read_manifest_entries(manifest_bytes)
        if len(entries) != anchors.evidence_records:
            raise RuntimeError(
                "3DS_CORPUS_INTEGRITY_FAILURE: "
                f"manifest listed {len(entries)} rows, expected {anchors.evidence_records}"
            )
        self._anchors = anchors
        self._entries = entries
        return anchors, entries

    @staticmethod
    def _certificate_record(ordinal: int, path: str, size: int, sha256: str) -> bytes:
        return f"{ordinal}\t{path}\t{size}\t{sha256}\n".encode("utf-8")

    def validate(
        self,
        certificate_path: Path,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> CorpusValidation:
        anchors, entries = self.inspect()
        certificate_path = certificate_path.expanduser().resolve()
        certificate_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = certificate_path.with_suffix(certificate_path.suffix + ".tmp")
        digest = hashlib.sha256()
        controls = (
            (1, MANIFEST_NAME, self.root / MANIFEST_NAME, anchors.manifest_sha256),
            (2, VALIDATION_NAME, self.root / VALIDATION_NAME, anchors.validation_sha256),
        )
        total = len(entries) + len(controls)
        try:
            with temporary_path.open("wb") as certificate:
                for ordinal, relative_path, path, expected_sha256 in controls:
                    value = path.read_bytes()
                    actual_sha256 = self._sha256_bytes(value)
                    if actual_sha256 != expected_sha256:
                        raise RuntimeError(
                            f"3DS_CORPUS_INTEGRITY_FAILURE: SHA-256 mismatch: {relative_path}"
                        )
                    self._parse_markdown(value, relative_path)
                    record = self._certificate_record(ordinal, relative_path, len(value), actual_sha256)
                    certificate.write(record)
                    digest.update(record)
                for entry in entries:
                    path = (self.root / Path(entry.relative_path)).resolve()
                    try:
                        value = path.read_bytes()
                    except OSError as exc:
                        raise RuntimeError(
                            f"3DS_CORPUS_INTEGRITY_FAILURE: evidence was not readable: {entry.relative_path}"
                        ) from exc
                    actual_sha256 = self._sha256_bytes(value)
                    if len(value) != entry.byte_count or actual_sha256 != entry.sha256:
                        raise RuntimeError(
                            f"3DS_CORPUS_INTEGRITY_FAILURE: evidence mismatch: {entry.relative_path}"
                        )
                    self._parse_markdown(value, entry.relative_path)
                    record = self._certificate_record(
                        entry.ordinal,
                        entry.relative_path,
                        entry.byte_count,
                        actual_sha256,
                    )
                    certificate.write(record)
                    digest.update(record)
                    if progress is not None and (
                        entry.ordinal == total or entry.ordinal % 5_000 == 0
                    ):
                        progress(entry.ordinal, total, entry.relative_path)
            certificate_sha256 = digest.hexdigest()
            if certificate_sha256 != anchors.certificate_sha256:
                raise RuntimeError(
                    "3DS_CORPUS_INTEGRITY_FAILURE: completion certificate SHA-256 did not match AGENTS.md"
                )
            temporary_path.replace(certificate_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        validation = CorpusValidation(
            root=self.root,
            document_count=len(entries) + 3,
            evidence_record_count=total,
            certificate_sha256=certificate_sha256,
            certificate_path=certificate_path,
        )
        self._validation = validation
        return validation

    def validated(self) -> CorpusValidation:
        if self._validation is None:
            raise RuntimeError("3DS_CORPUS_INTEGRITY_FAILURE: corpus gate has not completed")
        return self._validation

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {token.lower() for token in _WORD.findall(value) if len(token) >= 2}

    def _ranked_entries(self, query: str) -> Iterable[CorpusEntry]:
        self.validated()
        assert self._entries is not None
        query_tokens = self._tokens(query)
        release_tokens = {"2024x", "2024xr3", "twcloud2024xr3"}

        def score(entry: CorpusEntry) -> tuple[int, int]:
            path = entry.relative_path.lower()
            path_tokens = self._tokens(path)
            overlap = query_tokens & path_tokens
            value = len(overlap) * 10
            value += sum(6 for token in query_tokens if token in path)
            if release_tokens & query_tokens and any(token in path for token in release_tokens):
                value += 20
            if "current_authoritative_sources/" in path:
                value += 4
            if "legacy_pack/" in path:
                value -= 25
            return value, -entry.ordinal

        return (
            entry
            for entry in sorted(self._entries, key=score, reverse=True)
            if score(entry)[0] > 0
        )

    def control_documents(self) -> tuple[CorpusDocument, ...]:
        self.validated()
        names = (
            CONTROLLER_NAME,
            "00_FULL_SYSTEM_DIGEST.md",
            "00_TRUTH_RAILS.md",
            "00_VERSION_MATRIX.md",
            "00_MACHINE_ROUTING.md",
            "00_UNAVAILABLE_AND_BOUNDARIES.md",
            VALIDATION_NAME,
        )
        documents: list[CorpusDocument] = []
        for name in names:
            path = self.root / name
            content = self._parse_markdown(path.read_bytes(), name)
            documents.append(CorpusDocument(relative_path=name, content=content))
        return tuple(documents)

    def retrieve(
        self,
        query: str,
        *,
        maximum_documents: int = 12,
        maximum_characters: int = 120_000,
        maximum_document_characters: int = 30_000,
    ) -> tuple[CorpusDocument, ...]:
        self.validated()
        documents: list[CorpusDocument] = []
        remaining = maximum_characters
        for entry in self._ranked_entries(query):
            if len(documents) >= maximum_documents or remaining <= 0:
                break
            path = self.root / Path(entry.relative_path)
            content = self._parse_markdown(path.read_bytes(), entry.relative_path)
            allowance = min(remaining, maximum_document_characters)
            truncated = len(content) > allowance
            documents.append(
                CorpusDocument(
                    relative_path=entry.relative_path,
                    content=content[:allowance],
                    truncated=truncated,
                )
            )
            remaining -= min(len(content), allowance)
        return tuple(documents)
