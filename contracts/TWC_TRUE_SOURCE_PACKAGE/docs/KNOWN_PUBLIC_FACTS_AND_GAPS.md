# Known Public Facts and Gaps

## Publicly verified facts
1. Teamwork Cloud REST API documentation is provided in Swagger, publicly accessible at `https://osmc.nomagic.com`, and also accessible from a server installation at `https://<Teamwork Cloud IP>:8111/osmc/swagger`.
2. The raw public 2022xR2 and 2024xR3 OpenAPI specs both declare `"servers": [{"url": "http://localhost:8111"}]`, which matches the bundled Swagger location on port `8111`.
3. The public Swagger index has entries for both **2022x R2** and **2024x R3**, plus separate entries for **server-side simulation** documentation for those versions.
4. Teamwork Cloud 2024x Refresh3 documents **OpenID Connect** discovery, authorization-code and refresh grants, `scope=openid`, `client_secret_basic`, generated OAuth client credentials, and `Authorization: Token <ID token>` for REST.
5. Teamwork Cloud Authentication Server separately supports **SAML** as an upstream Service Provider integration; this does not make a Workbench web client a SAML client.
6. Teamwork Cloud docs warn that sessions remain open unless explicitly reused/logged out.
7. Teamwork Cloud docs describe model manipulation at the **EMF level**, with MagicDraw-specific extensions available to reduce call count for common model tasks.
8. 2024xR3 release notes mention **improvements to SSO support across command-line tools** and new publish templates for Cameo Collaborator documents.
9. Public Cameo / MagicDraw JDocs are available for both `2022x` and `2024x`, including the plugin, browser, specifications, Teamwork, OpenAPI UML, and UML symbols packages that matter for plugin capture and UI parity work.

## Project deployment assumption
1. For this project, treat `https://<host>:8443` as the browser-facing Teamwork Cloud web application endpoint.
2. Treat `https://<host>:8111/osmc/swagger` as the REST/Swagger endpoint used for contract export and API probing.
3. Assume the default Teamwork Cloud deployment layout and substitute only your HTTPS host name; no extra reverse proxy, path-base rewrite, or non-default URL layout is assumed.

## Gaps that public docs alone do not close
1. Exact Swagger/OpenAPI payloads for your live 2022xR2 and 2024xR3 servers.
2. Exact OIDC discovery response, registered redirect URI, TLS/proxy behavior, token claims, and upstream identity-provider behavior in your environment.
3. Exact collaborator/document/comment/version endpoints enabled in your deployment.
4. Exact server-side simulation payloads you rely on in production.
5. Exact error payloads: 401, 403, 404, 409, validation, capability restriction.
6. Exact internal publish service contract for PPT/doc generation and editable outputs.
7. The historical public link for `2022x Refresh2 Hot Fix 2 Version News` currently returns `404`, so version-history references for that specific page should be treated as stale until replaced with a working official source.

## Why the coding agent still needs live artifacts
A coding agent can use the public sources to build a **contract skeleton**, compare versions, and identify likely endpoint groups.
It cannot safely finalize a production implementation without the live artifacts above.
