#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def schema_ref_name(schema: Any) -> str | None:
    if isinstance(schema, dict) and "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    return None


def summarize_operation(path: str, method: str, op: Dict[str, Any]) -> Dict[str, Any]:
    parameters = op.get("parameters", [])
    req = op.get("requestBody", {})
    request_content = sorted((req.get("content") or {}).keys())
    request_refs = []
    for media, body in (req.get("content") or {}).items():
        ref_name = schema_ref_name(body.get("schema"))
        if ref_name:
            request_refs.append({"media": media, "schema_ref": ref_name})

    responses = {}
    for code, resp in (op.get("responses") or {}).items():
        content = resp.get("content") or {}
        refs = []
        for media, body in content.items():
            ref_name = schema_ref_name(body.get("schema"))
            if ref_name:
                refs.append({"media": media, "schema_ref": ref_name})
        responses[code] = {
            "description": resp.get("description"),
            "content_types": sorted(content.keys()),
            "schema_refs": refs,
        }

    return {
        "operationId": op.get("operationId"),
        "summary": op.get("summary"),
        "tags": op.get("tags", []),
        "path": path,
        "method": method.upper(),
        "parameter_names": [p.get("name") for p in parameters if isinstance(p, dict)],
        "parameter_in": {p.get("name"): p.get("in") for p in parameters if isinstance(p, dict)},
        "request_content_types": request_content,
        "request_schema_refs": request_refs,
        "response_summary": responses,
    }


def feature_group(path: str, tags: list[str]) -> str:
    text = (path + " " + " ".join(tags)).lower()
    if any(k in text for k in ["simulation", "execute", "run"]):
        return "simulation"
    if any(k in text for k in ["comment", "attachment", "document", "version"]):
        return "documents_collaboration"
    if any(k in text for k in ["search"]):
        return "search"
    if any(k in text for k in ["branch", "project", "resource", "element", "tree", "model"]):
        return "browse_model"
    if any(k in text for k in ["publish", "report", "export"]):
        return "publish"
    if any(k in text for k in ["auth", "login", "logout", "token", "session"]):
        return "auth_session"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser(description="Normalize OpenAPI into a compact comparison format")
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--label", default="unknown")
    args = ap.parse_args()

    data = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    paths = data.get("paths", {})
    components = data.get("components", {})
    schemas = (components.get("schemas") or {}) if isinstance(components, dict) else {}

    operations = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            summary = summarize_operation(path, method, op)
            summary["feature_group"] = feature_group(path, summary.get("tags", []))
            operations.append(summary)

    normalized = {
        "label": args.label,
        "title": data.get("info", {}).get("title"),
        "version": data.get("info", {}).get("version"),
        "servers": data.get("servers", []),
        "schema_count": len(schemas),
        "schema_names": sorted(schemas.keys()),
        "operation_count": len(operations),
        "operations": sorted(operations, key=lambda x: (x["path"], x["method"])),
    }

    out = Path(args.outfile)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    print(f"Normalized spec written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
