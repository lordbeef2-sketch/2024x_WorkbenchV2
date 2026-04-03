#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def load_ops(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ops = {}
    for op in data.get("operations", []):
        key = (op["path"], op["method"])
        ops[key] = op
    return data, ops


def op_signature(op: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tags": sorted(op.get("tags", [])),
        "parameter_names": sorted(op.get("parameter_names", [])),
        "request_content_types": sorted(op.get("request_content_types", [])),
        "request_schema_refs": sorted((x.get("schema_ref") for x in op.get("request_schema_refs", []) if x.get("schema_ref"))),
        "response_codes": sorted(op.get("response_summary", {}).keys()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff two normalized OpenAPI summaries")
    ap.add_argument("left")
    ap.add_argument("right")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    left_data, left_ops = load_ops(args.left)
    right_data, right_ops = load_ops(args.right)

    left_keys = set(left_ops.keys())
    right_keys = set(right_ops.keys())

    only_left = sorted(left_keys - right_keys)
    only_right = sorted(right_keys - left_keys)
    shared = sorted(left_keys & right_keys)

    changed = []
    for key in shared:
        l_sig = op_signature(left_ops[key])
        r_sig = op_signature(right_ops[key])
        if l_sig != r_sig:
            changed.append({
                "path": key[0],
                "method": key[1],
                "left": l_sig,
                "right": r_sig,
            })

    result = {
        "left_label": left_data.get("label"),
        "right_label": right_data.get("label"),
        "left_operation_count": left_data.get("operation_count"),
        "right_operation_count": right_data.get("operation_count"),
        "only_left": [{"path": p, "method": m} for p, m in only_left],
        "only_right": [{"path": p, "method": m} for p, m in only_right],
        "changed_shared_operations": changed,
        "shared_operation_count": len(shared),
        "schema_names_only_left": sorted(set(left_data.get("schema_names", [])) - set(right_data.get("schema_names", []))),
        "schema_names_only_right": sorted(set(right_data.get("schema_names", [])) - set(left_data.get("schema_names", []))),
    }

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = []
    lines.append(f"# OpenAPI Diff: {result['left_label']} vs {result['right_label']}")
    lines.append("")
    lines.append(f"- {result['left_label']} operation count: {result['left_operation_count']}")
    lines.append(f"- {result['right_label']} operation count: {result['right_operation_count']}")
    lines.append(f"- Shared operations: {result['shared_operation_count']}")
    lines.append(f"- Changed shared operations: {len(changed)}")
    lines.append("")
    lines.append("## Only in left")
    for item in result["only_left"][:200]:
        lines.append(f"- `{item['method']} {item['path']}`")
    if len(result["only_left"]) > 200:
        lines.append(f"- ... {len(result['only_left']) - 200} more")
    lines.append("")
    lines.append("## Only in right")
    for item in result["only_right"][:200]:
        lines.append(f"- `{item['method']} {item['path']}`")
    if len(result["only_right"]) > 200:
        lines.append(f"- ... {len(result['only_right']) - 200} more")
    lines.append("")
    lines.append("## Changed shared operations")
    for item in changed[:200]:
        lines.append(f"- `{item['method']} {item['path']}`")
    if len(changed) > 200:
        lines.append(f"- ... {len(changed) - 200} more")

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote diff JSON to {out_json}")
    print(f"Wrote diff report to {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
