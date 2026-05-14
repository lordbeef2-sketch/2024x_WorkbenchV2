from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


CONFIG_PATH = Path(__file__).with_name("workbench_cache_api_config.json")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def bearer_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def verify_value(config: dict[str, Any]) -> bool | str:
    verify_tls = config.get("verify_tls", True)
    return verify_tls


def request_json(
    method: str,
    base_url: str,
    path: str,
    api_key: str,
    *,
    payload: Any | None = None,
    verify: bool | str = True,
) -> Any:
    response = requests.request(
        method=method,
        url=build_url(base_url, path),
        headers={
            **bearer_headers(api_key),
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
        json=payload,
        timeout=60,
        verify=verify,
    )
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()
