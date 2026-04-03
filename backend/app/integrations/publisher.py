from __future__ import annotations

import asyncio
import html
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from zipfile import ZIP_DEFLATED, ZipFile

import httpx

from app.core.pdf import render_pdf_document
from app.models.domain import Capability, CapabilityState, PublishPreset, PublishRequest
from app.settings.config import Settings

ProgressReporter = Callable[[int, str], Awaitable[None]]
CancelChecker = Callable[[], bool]


class PublisherAdapter:
    def capability(self) -> Capability:
        raise NotImplementedError

    def presets(self) -> list[PublishPreset]:
        return [
            PublishPreset(
                id="review-board",
                name="Review Board Pack",
                template="board-deck",
                category="governance",
                description="Structured HTML package for architecture and safety review boards.",
            ),
            PublishPreset(
                id="collaborator-handout",
                name="Collaborator Handout",
                template="collaborator-handout",
                category="presentation",
                description="Reading-mode package for presentation and collaborator sharing.",
            ),
        ]

    async def publish(
        self,
        request: PublishRequest,
        output_dir: Path,
        report: ProgressReporter,
        cancel_requested: CancelChecker,
    ) -> dict[str, Any]:
        raise NotImplementedError


class LocalPublisherAdapter(PublisherAdapter):
    def capability(self) -> Capability:
        return Capability(
            name="publish",
            state=CapabilityState.READY,
            reason="Local publish packaging is enabled. It generates HTML, Markdown, JSON, ZIP, and PDF artifacts while keeping CLI and webhook delivery pluggable.",
            source="local",
        )

    def _summary_markdown(self, request: PublishRequest, generated_at: str) -> str:
        lines = [
            "# Publish Package",
            "",
            f"Generated at: {generated_at}",
            "",
            "## Target",
            "",
            f"- Project: {request.project_id}",
            f"- Branch: {request.branch_id}",
            f"- Scope: {request.scope}",
            f"- Template: {request.template}",
            f"- Category: {request.category}",
            f"- Republish: {request.republish}",
            f"- Open Result: {request.open_result}",
        ]
        if request.presets:
            lines.extend(["", "## Presets", "", "```json", json.dumps(request.presets, indent=2), "```"])
        lines.extend(
            [
                "",
                "## Notes",
                "",
                "This package can be reviewed locally, attached to collaborator workflows, or handed off to external CLI or webhook publishers.",
            ]
        )
        return "\n".join(lines)

    def _index_html(self, request: PublishRequest, generated_at: str, manifest_name: str, markdown_name: str, pdf_name: str, zip_name: str) -> str:
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Publish Package</title>"
            "<style>"
            "body{font-family:'IBM Plex Sans',Arial,sans-serif;margin:2rem;background:#f5f7fb;color:#14213d;}"
            ".card{background:#fff;border-radius:20px;padding:2rem;box-shadow:0 18px 50px rgba(20,33,61,.08);max-width:960px;margin:auto;}"
            "h1,h2{font-family:'Space Grotesk',sans-serif;margin-top:0;}"
            "ul{line-height:1.8;padding-left:1.2rem;}"
            "a{color:#0b5fff;text-decoration:none;font-weight:600;}"
            "code{background:#eef3fb;padding:.2rem .4rem;border-radius:6px;}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-top:1.5rem;}"
            ".tile{background:#f8fbff;border:1px solid #d7e3f6;border-radius:16px;padding:1rem;}"
            "</style></head><body><div class='card'>"
            f"<h1>Publish Package</h1><p>Generated at <code>{html.escape(generated_at)}</code>.</p>"
            "<h2>Target</h2><ul>"
            f"<li>Project: <code>{html.escape(request.project_id)}</code></li>"
            f"<li>Branch: <code>{html.escape(request.branch_id)}</code></li>"
            f"<li>Scope: <code>{html.escape(request.scope)}</code></li>"
            f"<li>Template: <code>{html.escape(request.template)}</code></li>"
            f"<li>Category: <code>{html.escape(request.category)}</code></li>"
            f"<li>Republish: <code>{request.republish}</code></li>"
            "</ul>"
            "<div class='grid'>"
            f"<div class='tile'><h2>Manifest</h2><p><a href='{html.escape(manifest_name)}'>Open JSON manifest</a></p></div>"
            f"<div class='tile'><h2>Markdown</h2><p><a href='{html.escape(markdown_name)}'>Open Markdown summary</a></p></div>"
            f"<div class='tile'><h2>PDF</h2><p><a href='{html.escape(pdf_name)}'>Open PDF summary</a></p></div>"
            f"<div class='tile'><h2>ZIP</h2><p><a href='{html.escape(zip_name)}'>Download package ZIP</a></p></div>"
            "</div></div></body></html>"
        )

    async def publish(
        self,
        request: PublishRequest,
        output_dir: Path,
        report: ProgressReporter,
        cancel_requested: CancelChecker,
    ) -> dict[str, Any]:
        steps = [
            (15, "Validating publish request"),
            (35, "Rendering review package"),
            (65, "Building PDF and metadata artifacts"),
            (85, "Bundling publish package"),
            (100, "Publish completed"),
        ]
        for progress, message in steps:
            if cancel_requested():
                return {"cancelled": True}
            await report(progress, message)
            await asyncio.sleep(0.25)

        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        bundle_dir = output_dir / f"publish-{request.project_id}-{request.branch_id}-{stamp}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "generated_at": stamp,
            "project_id": request.project_id,
            "branch_id": request.branch_id,
            "scope": request.scope,
            "template": request.template,
            "category": request.category,
            "republish": request.republish,
            "open_result": request.open_result,
            "presets": request.presets,
        }
        generated_at = datetime.now(UTC).isoformat()
        markdown = self._summary_markdown(request, generated_at)
        manifest_path = bundle_dir / "manifest.json"
        markdown_path = bundle_dir / "summary.md"
        pdf_path = bundle_dir / "summary.pdf"
        index_path = bundle_dir / "index.html"
        zip_path = output_dir / f"publish-{request.project_id}-{request.branch_id}-{stamp}.zip"

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        markdown_path.write_text(markdown, encoding="utf-8")
        pdf_path.write_bytes(render_pdf_document("Publish Package", markdown))
        index_path.write_text(
            self._index_html(
                request,
                generated_at,
                manifest_path.name,
                markdown_path.name,
                pdf_path.name,
                zip_path.name,
            ),
            encoding="utf-8",
        )

        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            for file_path in (index_path, manifest_path, markdown_path, pdf_path):
                archive.write(file_path, arcname=file_path.name)

        return {
            "artifact_path": str(index_path),
            "bundle_dir": str(bundle_dir),
            "bundle_zip": str(zip_path),
            "mode": "local",
        }


class CliPublisherAdapter(PublisherAdapter):
    def __init__(self, command: str) -> None:
        self.command = command

    def capability(self) -> Capability:
        return Capability(
            name="publish",
            state=CapabilityState.READY,
            reason="External CLI publisher is configured.",
            source="integration",
        )

    async def publish(
        self,
        request: PublishRequest,
        output_dir: Path,
        report: ProgressReporter,
        cancel_requested: CancelChecker,
    ) -> dict[str, Any]:
        if cancel_requested():
            return {"cancelled": True}
        await report(20, "Executing external publisher CLI")
        payload_path = output_dir / "publish-request.json"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
        completed = await asyncio.to_thread(
            subprocess.run,
            self.command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )
        await report(100, "External publisher finished")
        return {
            "mode": "cli",
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "payload_path": str(payload_path),
        }


class WebhookPublisherAdapter(PublisherAdapter):
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def capability(self) -> Capability:
        return Capability(
            name="publish",
            state=CapabilityState.READY,
            reason="External webhook publisher is configured.",
            source="integration",
        )

    async def publish(
        self,
        request: PublishRequest,
        output_dir: Path,
        report: ProgressReporter,
        cancel_requested: CancelChecker,
    ) -> dict[str, Any]:
        if cancel_requested():
            return {"cancelled": True}
        await report(35, "Submitting publish request to external job endpoint")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.webhook_url, json=request.model_dump(mode="json"))
            response.raise_for_status()
        await report(100, "Webhook publisher acknowledged the request")
        return {"mode": "webhook", "response": response.json() if response.content else {}}


def build_publisher(settings: Settings) -> PublisherAdapter:
    mode = settings.publisher_mode.strip().lower()
    if mode == "cli" and settings.publisher_command:
        return CliPublisherAdapter(settings.publisher_command)
    if mode == "webhook" and settings.publisher_webhook_url:
        return WebhookPublisherAdapter(settings.publisher_webhook_url)
    return LocalPublisherAdapter()
