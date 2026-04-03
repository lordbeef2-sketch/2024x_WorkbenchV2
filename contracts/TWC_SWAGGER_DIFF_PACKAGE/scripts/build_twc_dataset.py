#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent


def run(cmd):
    print("RUN:", " ".join(str(x) for x in cmd))
    subprocess.run([str(x) for x in cmd], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot fetch + normalize + diff for TWC Swagger")
    ap.add_argument("--v2022-url", required=True)
    ap.add_argument("--v2024-url", required=True)
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    raw = outdir / "swagger" / "raw"
    norm = outdir / "swagger" / "normalized"
    diffs = outdir / "diffs"
    reports = outdir / "reports"

    raw.mkdir(parents=True, exist_ok=True)
    norm.mkdir(parents=True, exist_ok=True)
    diffs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    fetch = THIS_DIR / "fetch_twc_swagger.py"
    normalize = THIS_DIR / "normalize_openapi.py"
    diff = THIS_DIR / "diff_openapi_versions.py"

    insecure = ["--insecure"] if args.insecure else []

    run([sys.executable, fetch, args.v2022_url, raw / "twc_2022xR2.json", *insecure])
    run([sys.executable, fetch, args.v2024_url, raw / "twc_2024xR3.json", *insecure])

    run([sys.executable, normalize, raw / "twc_2022xR2.json", norm / "twc_2022xR2_normalized.json", "--label", "2022xR2"])
    run([sys.executable, normalize, raw / "twc_2024xR3.json", norm / "twc_2024xR3_normalized.json", "--label", "2024xR3"])

    run([
        sys.executable,
        diff,
        norm / "twc_2022xR2_normalized.json",
        norm / "twc_2024xR3_normalized.json",
        "--out-json", diffs / "twc_diff.json",
        "--out-md", reports / "twc_diff_report.md",
    ])

    print("Dataset build complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
