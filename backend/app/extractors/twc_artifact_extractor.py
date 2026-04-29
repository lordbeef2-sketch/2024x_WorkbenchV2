from __future__ import annotations

"""
Artifact-first Teamwork Cloud extractor.

Why this module starts at artifacts instead of elements:
RealSwagger.json for this project exposes branch artifact listing and branch batch
element retrieval, but it does not expose a root GET endpoint that lists every
element in a branch. Because of that contract boundary, the extractor must:

1. list branch artifacts,
2. inspect artifact payloads for UUID-like references,
3. classify likely element IDs,
4. batch-fetch elements only after discovery.

This keeps the workflow aligned to the validated Swagger rather than inventing an
unsupported wildcard or hidden element-listing path.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from requests import Response, Session
from requests.exceptions import RequestException


UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
ARTIFACT_LIMITATION_MESSAGE = (
    "Swagger supports artifact listing and batch element fetch, but did not expose a full element listing path from artifact data."
)
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "twc_artifact_extractor.sqlite3"


class ExtractorError(RuntimeError):
    """Raised when a Swagger-backed extractor request fails."""


@dataclass(slots=True)
class ExtractorConfig:
    base_url: str
    token: str
    workspace_id: str
    resource_id: str
    branch_id: str
    verify_tls: bool | str = True
    chunk_size: int = 200
    request_timeout_seconds: int = 30
    cache_path: Path = DEFAULT_CACHE_PATH
    refresh_discovery: bool = False

    @property
    def scope_key(self) -> str:
        return json.dumps(
            {
                "base_url": normalize_base_url(self.base_url),
                "workspace_id": self.workspace_id,
                "resource_id": self.resource_id,
                "branch_id": self.branch_id,
            },
            sort_keys=True,
        )

    @property
    def api_root(self) -> str:
        return normalize_base_url(self.base_url)

    @property
    def requests_verify(self) -> bool | str:
        return parse_verify_tls(self.verify_tls)


@dataclass(slots=True)
class DiscoveryState:
    artifact_ids: set[str] = field(default_factory=set)
    possible_element_ids: set[str] = field(default_factory=set)
    model_ids: set[str] = field(default_factory=set)
    unknown_ids: set[str] = field(default_factory=set)
    sources: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add(self, classification: str, identifier: str, source: str) -> None:
        bucket = getattr(self, classification)
        bucket.add(identifier)
        self.sources[identifier].add(source)

    def merge(self, other: "DiscoveryState") -> None:
        self.artifact_ids.update(other.artifact_ids)
        self.possible_element_ids.update(other.possible_element_ids)
        self.model_ids.update(other.model_ids)
        self.unknown_ids.update(other.unknown_ids)
        for identifier, sources in other.sources.items():
            self.sources[identifier].update(sources)

    def as_cache_payload(self) -> dict[str, Any]:
        return {
            "artifact_ids": sorted(self.artifact_ids),
            "possible_element_ids": sorted(self.possible_element_ids),
            "model_ids": sorted(self.model_ids),
            "unknown_ids": sorted(self.unknown_ids),
            "sources": {identifier: sorted(values) for identifier, values in self.sources.items()},
        }

    @classmethod
    def from_cache_payload(cls, payload: dict[str, Any]) -> "DiscoveryState":
        state = cls(
            artifact_ids={str(item) for item in payload.get("artifact_ids", [])},
            possible_element_ids={str(item) for item in payload.get("possible_element_ids", [])},
            model_ids={str(item) for item in payload.get("model_ids", [])},
            unknown_ids={str(item) for item in payload.get("unknown_ids", [])},
        )
        for identifier, sources in payload.get("sources", {}).items():
            state.sources[str(identifier)].update(str(source) for source in sources)
        return state


@dataclass(slots=True)
class BatchFetchResult:
    fetched_elements: dict[str, Any] = field(default_factory=dict)
    fetched_ids: set[str] = field(default_factory=set)
    rejected_ids: set[str] = field(default_factory=set)
    failed_chunks: list[str] = field(default_factory=list)


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/osmc"):
        return normalized[: -len("/osmc")]
    return normalized


def parse_verify_tls(value: bool | str) -> bool | str:
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in {"0", "false", "no", "off"}:
        return False
    if lowered in {"1", "true", "yes", "on"}:
        return True
    return text


def build_session(config: ExtractorConfig) -> Session:
    session = requests.Session()
    token = config.token.strip()
    if not token:
        raise ExtractorError("A bearer token is required.")

    if " " in token:
        authorization = token
    else:
        authorization = f"Bearer {token}"

    session.headers.update(
        {
            "Authorization": authorization,
            "Accept": "application/ld+json, application/json;q=0.9, */*;q=0.8",
        }
    )
    return session


def build_url(config: ExtractorConfig, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{config.api_root}{path}"


def _request_json(
    session: Session,
    config: ExtractorConfig,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    data: str | bytes | None = None,
    content_type: str | None = None,
    allow_not_found: bool = False,
) -> tuple[Any | None, Response]:
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type

    try:
        response = session.request(
            method=method,
            url=build_url(config, path),
            params=params,
            data=data,
            headers=headers,
            timeout=config.request_timeout_seconds,
            verify=config.requests_verify,
        )
    except RequestException as exc:
        raise ExtractorError(f"{method} {path} failed before a response was returned: {exc}") from exc

    if response.status_code == 404 and allow_not_found:
        return None, response

    if response.status_code == 401:
        raise ExtractorError(f"{method} {path} returned 401 Unauthorized.")
    if response.status_code == 403:
        raise ExtractorError(f"{method} {path} returned 403 Forbidden.")
    if response.status_code == 404:
        raise ExtractorError(f"{method} {path} returned 404 Not Found.")
    if response.status_code == 409:
        raise ExtractorError(f"{method} {path} returned 409 Conflict: {response.text.strip() or 'request conflicted with current server state.'}")
    if response.status_code >= 500:
        raise ExtractorError(f"{method} {path} returned {response.status_code}: {response.text.strip() or 'server error'}")
    if response.status_code >= 400:
        raise ExtractorError(f"{method} {path} returned {response.status_code}: {response.text.strip() or 'request failed'}")

    if not response.content:
        return {}, response

    try:
        return response.json(), response
    except ValueError as exc:
        raise ExtractorError(
            f"{method} {path} returned {response.status_code} but the body was not valid JSON-LD/JSON."
        ) from exc


def _extract_uuid_candidates(value: Any) -> set[str]:
    candidates: set[str] = set()
    if value is None:
        return candidates

    text = str(value)
    for match in UUID_PATTERN.findall(text):
        candidates.add(match.lower())

    if isinstance(value, str):
        parsed = urlparse(value)
        fragments = [parsed.fragment, *(segment for segment in parsed.path.split("/") if segment)]
        for fragment in fragments:
            if not fragment:
                continue
            for match in UUID_PATTERN.findall(fragment):
                candidates.add(match.lower())

    return candidates


def _next_page_reference(payload: Any, response: Response) -> str | None:
    link_header = response.headers.get("Link", "")
    if link_header:
        for part in link_header.split(","):
            if 'rel="next"' not in part:
                continue
            start = part.find("<")
            end = part.find(">", start + 1)
            if start >= 0 and end > start:
                return part[start + 1 : end]

    if not isinstance(payload, dict):
        return None

    for key in ("hydra:next", "ldp:nextPage", "next", "nextPage"):
        next_value = payload.get(key)
        if isinstance(next_value, str) and next_value.strip():
            return next_value.strip()
        if isinstance(next_value, dict):
            for nested_key in ("@id", "id", "href"):
                nested_value = next_value.get(nested_key)
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value.strip()
    return None


def list_branch_artifacts(config: ExtractorConfig, session: Session) -> tuple[list[str], list[Any]]:
    """List artifacts from the Swagger-supported branch artifact container."""

    path = f"/osmc/workspaces/{config.workspace_id}/resources/{config.resource_id}/branches/{config.branch_id}/artifacts"
    pending_reference: str | None = path
    seen_references: set[str] = set()
    discovered_artifact_ids: list[str] = []
    payloads: list[Any] = []

    while pending_reference and pending_reference not in seen_references:
        seen_references.add(pending_reference)
        payload, response = _request_json(session, config, "GET", pending_reference)
        payloads.append(payload)

        contains = payload.get("ldp:contains", []) if isinstance(payload, dict) else []
        for item in contains if isinstance(contains, list) else []:
            for candidate in _extract_uuid_candidates(item):
                if candidate not in discovered_artifact_ids:
                    discovered_artifact_ids.append(candidate)

        pending_reference = _next_page_reference(payload, response)

    logging.info("Artifact IDs discovered (%s): %s", len(discovered_artifact_ids), ", ".join(discovered_artifact_ids) or "none")
    return discovered_artifact_ids, payloads


def get_artifact_detail(config: ExtractorConfig, session: Session, artifact_id: str) -> dict[str, Any] | None:
    """Fetch one artifact detail document from the Swagger-supported artifact detail endpoint."""

    path = (
        f"/osmc/workspaces/{config.workspace_id}/resources/{config.resource_id}"
        f"/branches/{config.branch_id}/artifacts/{artifact_id}"
    )
    payload, response = _request_json(session, config, "GET", path, params={"download": "false"}, allow_not_found=True)
    if response.status_code == 404:
        logging.warning("Artifact detail not found for artifact %s", artifact_id)
        return None
    return payload if isinstance(payload, dict) else {"raw": payload}


def extract_uuid_references(payload: Any, artifact_ids: set[str] | None = None) -> DiscoveryState:
    """
    Recursively extract UUID-like values from JSON-LD artifact payloads.

    Known artifact IDs win classification first so the extractor does not treat the
    artifact container's own ldp:contains values as elements.
    """

    artifact_ids = {identifier.lower() for identifier in artifact_ids or set()}
    state = DiscoveryState(artifact_ids=set(artifact_ids))
    element_keys = {"@id", "kerml:esiid", "ldp:contains", "kerml:ownedelement", "kerml:packagedelement", "kerml:owner"}

    def classify(path_segments: list[str], identifier: str) -> str:
        lowered_segments = [segment.lower() for segment in path_segments if segment]
        lowered_path = ".".join(lowered_segments)
        last_segment = lowered_segments[-1] if lowered_segments else ""

        if identifier in artifact_ids or "artifact" in lowered_path:
            return "artifact_ids"
        if "model" in lowered_path or last_segment.startswith("model"):
            return "model_ids"
        if last_segment in element_keys or "element" in lowered_path:
            return "possible_element_ids"
        return "unknown_ids"

    def walk(node: Any, path_segments: list[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = [*path_segments, key]
                for identifier in _extract_uuid_candidates(value):
                    classification = classify(next_path, identifier)
                    state.add(classification, identifier, ".".join(next_path))
                walk(value, next_path)
            return

        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, [*path_segments, f"[{index}]"])
            return

        if isinstance(node, str):
            for identifier in _extract_uuid_candidates(node):
                classification = classify(path_segments, identifier)
                state.add(classification, identifier, ".".join(path_segments) or "<root>")

    walk(payload, [])
    state.possible_element_ids.difference_update(state.artifact_ids)
    state.model_ids.difference_update(state.artifact_ids)
    state.unknown_ids.difference_update(state.artifact_ids | state.possible_element_ids | state.model_ids)
    return state


def batch_fetch_elements(
    config: ExtractorConfig,
    session: Session,
    element_ids: Iterable[str],
    *,
    chunk_size: int | None = None,
) -> BatchFetchResult:
    """Batch-fetch discovered element IDs through the Swagger-supported POST /elements endpoint."""

    ids = [identifier.lower() for identifier in element_ids if identifier]
    if not ids:
        return BatchFetchResult()

    chunk_size = chunk_size or config.chunk_size
    result = BatchFetchResult()
    path = (
        f"/osmc/workspaces/{config.workspace_id}/resources/{config.resource_id}"
        f"/branches/{config.branch_id}/elements"
    )

    for start_index in range(0, len(ids), chunk_size):
        chunk = ids[start_index : start_index + chunk_size]
        body = ",".join(chunk)
        try:
            payload, _ = _request_json(
                session,
                config,
                "POST",
                path,
                data=body,
                content_type="text/plain",
            )
        except ExtractorError as exc:
            logging.error("Element batch request failed for chunk %s-%s: %s", start_index + 1, start_index + len(chunk), exc)
            result.failed_chunks.append(f"{start_index + 1}-{start_index + len(chunk)}")
            result.rejected_ids.update(chunk)
            continue

        if not isinstance(payload, dict):
            logging.warning("Unexpected batch element payload type for chunk %s-%s: %s", start_index + 1, start_index + len(chunk), type(payload).__name__)
            result.failed_chunks.append(f"{start_index + 1}-{start_index + len(chunk)}")
            result.rejected_ids.update(chunk)
            continue

        fetched_this_chunk = {identifier.lower() for identifier in payload.keys() if UUID_PATTERN.fullmatch(str(identifier))}
        rejected_this_chunk = set(chunk) - fetched_this_chunk
        result.fetched_ids.update(fetched_this_chunk)
        result.rejected_ids.update(rejected_this_chunk)
        for identifier, element_payload in payload.items():
            result.fetched_elements[str(identifier).lower()] = element_payload

        logging.info(
            "Elements successfully fetched (%s/%s) for chunk %s-%s",
            len(fetched_this_chunk),
            len(chunk),
            start_index + 1,
            start_index + len(chunk),
        )
        if rejected_this_chunk:
            logging.warning("IDs rejected or not found in chunk %s-%s: %s", start_index + 1, start_index + len(chunk), ", ".join(sorted(rejected_this_chunk)))

    return result


def _ensure_cache_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_extractor_cache (
            scope_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def load_cached_ids(cache_path: Path, config: ExtractorConfig) -> DiscoveryState | None:
    if not cache_path.exists():
        return None

    with sqlite3.connect(cache_path) as connection:
        _ensure_cache_schema(connection)
        row = connection.execute(
            "SELECT payload_json FROM artifact_extractor_cache WHERE scope_key = ?",
            (config.scope_key,),
        ).fetchone()
    if not row:
        return None

    payload = json.loads(row[0])
    return DiscoveryState.from_cache_payload(payload)


def cache_ids(cache_path: Path, config: ExtractorConfig, discovery: DiscoveryState) -> None:
    """Persist discovered IDs locally so future runs can skip full artifact discovery."""

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cache_path) as connection:
        _ensure_cache_schema(connection)
        connection.execute(
            """
            INSERT INTO artifact_extractor_cache (scope_key, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(scope_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                config.scope_key,
                json.dumps(discovery.as_cache_payload(), sort_keys=True),
                datetime.now(UTC).isoformat(),
            ),
        )
        connection.commit()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover Teamwork Cloud element IDs through branch artifacts, then batch-fetch elements without manual ID entry."
    )
    parser.add_argument("--base-url", default=os.getenv("TWC_BASE_URL", ""), help="TWC base URL, with or without /osmc.")
    parser.add_argument("--token", default=os.getenv("TWC_TOKEN", ""), help="Bearer token or full Authorization header value.")
    parser.add_argument("--workspace-id", default=os.getenv("TWC_WORKSPACE_ID", ""), help="Swagger workspaceId value.")
    parser.add_argument("--resource-id", default=os.getenv("TWC_RESOURCE_ID", ""), help="Swagger resourceId/projectId value.")
    parser.add_argument("--branch-id", default=os.getenv("TWC_BRANCH_ID", ""), help="Swagger branchId value.")
    parser.add_argument(
        "--verify-tls",
        default=os.getenv("TWC_VERIFY_TLS", "true"),
        help="true, false, or a CA bundle path.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=int(os.getenv("TWC_CHUNK_SIZE", "200")),
        help="Batch size for POST /elements requests.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        default=int(os.getenv("TWC_REQUEST_TIMEOUT_SECONDS", "30")),
        help="HTTP timeout for each request.",
    )
    parser.add_argument(
        "--cache-path",
        default=os.getenv("TWC_EXTRACTOR_CACHE_PATH", str(DEFAULT_CACHE_PATH)),
        help="SQLite cache path for discovered IDs.",
    )
    parser.add_argument(
        "--refresh-discovery",
        action="store_true",
        help="Ignore cached artifact discovery and walk the branch artifacts again.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)

    required = {
        "base_url": args.base_url,
        "token": args.token,
        "workspace_id": args.workspace_id,
        "resource_id": args.resource_id,
        "branch_id": args.branch_id,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        parser.error(f"Missing required configuration: {', '.join(missing)}")

    config = ExtractorConfig(
        base_url=args.base_url,
        token=args.token,
        workspace_id=args.workspace_id,
        resource_id=args.resource_id,
        branch_id=args.branch_id,
        verify_tls=args.verify_tls,
        chunk_size=max(1, args.chunk_size),
        request_timeout_seconds=max(1, args.request_timeout_seconds),
        cache_path=Path(args.cache_path),
        refresh_discovery=args.refresh_discovery,
    )

    session = build_session(config)

    try:
        discovery = None if config.refresh_discovery else load_cached_ids(config.cache_path, config)
        if discovery is not None:
            logging.info(
                "Loaded cached discovery for %s artifacts, %s possible element IDs, %s model IDs, %s unknown IDs.",
                len(discovery.artifact_ids),
                len(discovery.possible_element_ids),
                len(discovery.model_ids),
                len(discovery.unknown_ids),
            )
        else:
            discovery = DiscoveryState()
            artifact_ids, artifact_payloads = list_branch_artifacts(config, session)
            discovery.artifact_ids.update(artifact_ids)
            for payload in artifact_payloads:
                discovery.merge(extract_uuid_references(payload, artifact_ids=set(artifact_ids)))

            for artifact_id in artifact_ids:
                payload = get_artifact_detail(config, session, artifact_id)
                if payload is None:
                    continue
                artifact_state = extract_uuid_references(payload, artifact_ids=set(artifact_ids))
                discovery.merge(artifact_state)

            cache_ids(config.cache_path, config, discovery)

        logging.info(
            "Possible element IDs extracted (%s): %s",
            len(discovery.possible_element_ids),
            ", ".join(sorted(discovery.possible_element_ids)) or "none",
        )
        logging.info(
            "Model IDs extracted (%s): %s",
            len(discovery.model_ids),
            ", ".join(sorted(discovery.model_ids)) or "none",
        )
        logging.info(
            "Unknown UUID references extracted (%s): %s",
            len(discovery.unknown_ids),
            ", ".join(sorted(discovery.unknown_ids)) or "none",
        )

        if not discovery.possible_element_ids:
            logging.warning(ARTIFACT_LIMITATION_MESSAGE)
            print(ARTIFACT_LIMITATION_MESSAGE)
            return 0

        batch_result = batch_fetch_elements(
            config,
            session,
            sorted(discovery.possible_element_ids),
            chunk_size=config.chunk_size,
        )
        logging.info("Elements successfully fetched total: %s", len(batch_result.fetched_ids))
        logging.info("IDs rejected or not found total: %s", len(batch_result.rejected_ids))
        if batch_result.rejected_ids:
            logging.warning("Rejected/not found IDs: %s", ", ".join(sorted(batch_result.rejected_ids)))
        if batch_result.failed_chunks:
            logging.warning("Failed chunks: %s", ", ".join(batch_result.failed_chunks))

        print(
            json.dumps(
                {
                    "artifact_ids": sorted(discovery.artifact_ids),
                    "possible_element_ids": sorted(discovery.possible_element_ids),
                    "model_ids": sorted(discovery.model_ids),
                    "unknown_ids": sorted(discovery.unknown_ids),
                    "fetched_element_ids": sorted(batch_result.fetched_ids),
                    "rejected_element_ids": sorted(batch_result.rejected_ids),
                    "cache_path": str(config.cache_path),
                },
                indent=2,
            )
        )
        return 0
    except ExtractorError as exc:
        logging.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
