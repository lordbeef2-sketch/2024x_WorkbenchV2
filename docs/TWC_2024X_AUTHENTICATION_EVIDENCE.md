<!-- Created by: Raymond Reeves Engineering Tech 4 2026 -->
# TWC 2024x authentication evidence boundary

This file records what Workbench may claim and implement from the bundled 3DS
2024x source package. It prevents implementation details from being mistaken
for product documentation.

## Documented by official 2024x Refresh3 sources

The Developer Guide page `OpenID Connect authentication` documents the 2024x
OpenID web-application contract:

- Discovery: `/authentication/.well-known/oidc-configuration`
- Authorization endpoint: `/authentication/oidc/authorize`
- Token endpoint: `/authentication/api/oidc/token`
- Token endpoint authentication: `client_secret_basic`
- Supported scope: `openid`
- Supported grants include `authorization_code` and `refresh_token`
- OIDC clients are registered under Web Application Platform Settings ->
  OAuth clients -> OpenID Connect, which generates the client secret.
- TWC REST receives the returned ID token as `Authorization: Token <ID token>`.

Official URL:
`https://docs.nomagic.com/spaces/DEVG2024xR3/pages/225347498/OpenID+Connect+authentication`

The Teamwork Cloud token-based authentication documentation also documents the
AuthServer `authserver.properties` Application ID(s) flow:

- Application callback whitelist: `authentication.redirect.uri.whitelist`
- Application/client IDs: `authentication.client.ids`
- Authorization endpoint: `/authentication/authorize`
- Token endpoint: `/authentication/api/token`
- Token endpoint secret transport: `X-Auth-Secret`
- TWC REST receives the returned ID token as `Authorization: Token <ID token>`.

Official URL:
`https://docs.nomagic.com/spaces/TWCloud2024x/pages/137987741/Token-based+authentication`

## Implemented Workbench sign-in lanes

Workbench sign-in is selected per server profile:

- Authentication ID method uses the AuthServer Application ID(s) lane,
  defaults to `/authentication/authorize` and `/authentication/api/token`,
  exchanges the returned code with `X-Auth-Secret`, and validates the user
  against `/osmc/admin/currentUser`.
- OpenID uses the 2024x OpenID lane with discovery or explicit authorize/token
  URLs and the configured OpenID token authentication method.
- OAuth is reserved for OSLC/RealSwagger consumer configuration and is not a
  Workbench browser sign-in lane.

SAML is not the Workbench-to-AuthServer protocol. A deployment may configure
SAML as the Authentication Server's upstream identity provider while Workbench
continues to use the selected AuthServer lane.

## Not established by the package

- The package does not define a consumer-key/request-token/HMAC-SHA1 OSLC
  authentication exchange for Workbench.
- The package does not provide enough evidence to implement a replacement OSLC
  authentication exchange safely.
- Generic OAuth terminology or an existing code path is not evidence of the
  protocol supported by a live TWC installation.

Therefore Workbench does not treat OAuth/OSLC as a verified browser sign-in
path. OAuth/OSLC consumer fields may be stored in a server profile, but they
must remain separate from Authentication ID and OpenID sign-in behavior until a
live endpoint contract and successful/failing request captures are added and
tested.

## Required evidence for future OSLC resource work

OIDC authentication is established independently of whether an OSLC resource
surface is later implemented. OSLC work still requires:

1. A live root-services or resource-discovery response.
2. The exact resource URLs and supported media types.
3. One sanitized successful resource request and representative failures.
4. Confirmation that the same OIDC ID token is accepted for those resources.

Do not infer any missing item from OAuth field-name similarities.
