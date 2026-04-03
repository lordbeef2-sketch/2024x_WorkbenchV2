#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning


def fetch_text(url: str, verify: bool, timeout: int) -> requests.Response:
    if not verify:
        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
    resp = requests.get(url, verify=verify, timeout=timeout)
    resp.raise_for_status()
    return resp


def try_parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def find_spec_link(base_url: str, html: str) -> Optional[str]:
    patterns = [
        r'url\s*:\s*["\']([^"\']+)["\']',
        r'"swaggerUrl"\s*:\s*"([^"]+)"',
        r'href=["\']([^"\']*(?:openapi|swagger)[^"\']*\.json[^"\']*)["\']',
        r'src=["\']([^"\']*(?:openapi|swagger)[^"\']*\.json[^"\']*)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            link = m.group(1)
            return requests.compat.urljoin(base_url, link)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch TWC Swagger/OpenAPI JSON")
    ap.add_argument("url", help="Swagger page or raw spec URL")
    ap.add_argument("outfile", help="Where to save the JSON spec")
    ap.add_argument("--insecure", action="store_true", help="Disable SSL verification")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    verify = not args.insecure
    resp = fetch_text(args.url, verify=verify, timeout=args.timeout)
    data = try_parse_json(resp.text)
    if data is None:
        spec_url = find_spec_link(args.url, resp.text)
        if not spec_url:
            raise SystemExit("Could not parse JSON and could not find linked JSON spec from the swagger page.")
        resp = fetch_text(spec_url, verify=verify, timeout=args.timeout)
        data = try_parse_json(resp.text)
        if data is None:
            raise SystemExit(f"Linked spec did not return valid JSON: {spec_url}")

    out = Path(args.outfile)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved spec to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
