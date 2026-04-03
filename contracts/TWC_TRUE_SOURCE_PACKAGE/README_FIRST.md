# TWC True Source Package

This package is built to support a GPT-5.4 XHigh coding agent working on a **real** Teamwork Cloud integration for:
- Teamwork Cloud **2022x Refresh 2**
- Teamwork Cloud **2024x Refresh 3**

## What is inside
- `docs/` official-source manifest, version notes, collection checklist, and gap list.
- `prompts/` production prompt(s) for the coding agent.
- `scripts/` PowerShell and Python helpers to collect public and live source-of-truth data.
- `live_capture/` folders where live-server Swagger exports, HAR files, JSON responses, and error payloads should be placed.
- `official_html/` target filenames for downloaded public pages.

## No fake data policy
This package intentionally contains **no fabricated API samples**.
Any sample payloads or contracts used later should come from:
1. Public official docs / Swagger.
2. Your live 2022xR2 and 2024xR3 servers.
3. Your internal publish service.

## What is already verified publicly
Public official docs confirm that:
- Teamwork Cloud exposes REST API docs in Swagger at `https://<Teamwork Cloud IP>:8111/osmc/swagger` and publicly at `https://osmc.nomagic.com`.
- The raw public 2022xR2 and 2024xR3 OpenAPI documents both declare `http://localhost:8111` as the server URL, so `8111` is the documented REST/Swagger port.
- For this project, assume the default Teamwork Cloud layout with only your HTTPS host name substituted: browser UI at `https://<host>:8443` and REST/Swagger at `https://<host>:8111/osmc/swagger`. Do not use `8443` as the REST/Swagger base URL.
- The public Swagger index includes entries for **2022x R2** and **2024x R3**, plus separate **server-side simulation** docs for those versions.
- Teamwork Cloud authentication server supports **SAML**, where the authentication server acts as the Service Provider.
- Token-based authentication for REST is documented for both 2022xR2 and 2024x-era docs.
- Teamwork Cloud sessions remain open unless reused/logged out, which matters for automation and licensing.

## What still requires live capture
Public docs are not enough to verify your exact environment for:
- enabled endpoints on your servers,
- actual auth/session behavior after SAML in your environment,
- exact 401/403/404/409 payloads,
- collaborator/document behaviors in your deployment,
- your internal publish service contract,
- exact differences between public docs and your live server config beyond the default host substitution.

## Recommended workflow
1. Read `docs/OFFICIAL_SOURCE_MANIFEST.md`.
2. Run `scripts/fetch_public_sources.ps1` to save public official pages locally.
3. Export live Swagger/OpenAPI and save it into:
   - `live_capture/2022xR2/swagger/`
   - `live_capture/2024xR3/swagger/`
4. Capture real success/error payloads using `scripts/live_capture_playbook.md`.
5. Hand the whole package to GPT-5.4 XHigh with `prompts/GPT54_XHIGH_REVIEW_PROMPT.md`.

## Important
This package is meant to keep the coding agent grounded in **true sources only**.
