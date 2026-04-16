from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, quote, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from app.models.domain import OSLCConsumerCredentials, OSLCRootServicesSummary, OSLCTokenBundle, ServerProfile
from app.settings.config import Settings


def _xml_local_name(value: str) -> str:
    if "}" in value:
        return value.rsplit("}", 1)[-1]
    return value


def _xml_attr_resource(element: ElementTree.Element) -> str | None:
    for key, value in element.attrib.items():
        if _xml_local_name(key) == "resource" and value:
            return value.strip()
    text = (element.text or "").strip()
    return text or None


def _oauth_percent_encode(value: str) -> str:
    return quote(value, safe="~-._")


def _oauth_nonce() -> str:
    return secrets.token_hex(16)


def _oauth_timestamp() -> str:
    return str(int(datetime.now(UTC).timestamp()))


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = 80 if scheme == "http" else 443
    if port and port != default_port:
        host = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunparse((scheme, host, path, "", "", ""))


def _oauth_signature(
    method: str,
    url: str,
    params: dict[str, str],
    consumer_secret: str,
    token_secret: str = "",
) -> str:
    parsed = urlparse(url)
    query_params = parse_qsl(parsed.query, keep_blank_values=True)
    normalized_pairs = [
        (_oauth_percent_encode(key), _oauth_percent_encode(value))
        for key, value in [*query_params, *params.items()]
        if key != "oauth_signature"
    ]
    normalized_pairs.sort()
    parameter_string = "&".join(f"{key}={value}" for key, value in normalized_pairs)
    base_parts = [
        method.upper(),
        _oauth_percent_encode(_normalized_url(url)),
        _oauth_percent_encode(parameter_string),
    ]
    base_string = "&".join(base_parts)
    signing_key = f"{_oauth_percent_encode(consumer_secret)}&{_oauth_percent_encode(token_secret)}"
    digest = hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _oauth_authorization_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    *,
    callback_url: str | None = None,
    token: str | None = None,
    token_secret: str = "",
    verifier: str | None = None,
) -> str:
    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": _oauth_nonce(),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": _oauth_timestamp(),
        "oauth_version": "1.0",
    }
    if callback_url:
        params["oauth_callback"] = callback_url
    if token:
        params["oauth_token"] = token
    if verifier:
        params["oauth_verifier"] = verifier
    params["oauth_signature"] = _oauth_signature(method, url, params, consumer_secret, token_secret=token_secret)
    pairs = ", ".join(
        f'{_oauth_percent_encode(key)}="{_oauth_percent_encode(value)}"'
        for key, value in sorted(params.items())
    )
    return f"OAuth {pairs}"


@dataclass(slots=True)
class OSLCDiscoveryResult:
    summary: OSLCRootServicesSummary
    rootservices_text: str


class OAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _override(self, server: ServerProfile):
        return self.settings.twc_auth_override_for_server(server.id)

    def consumer_key(self, server: ServerProfile) -> str | None:
        override = self._override(server)
        return (override.oslc_consumer_key if override and override.oslc_consumer_key else None) or self.settings.resolved_twc_oslc_consumer_key

    def consumer_secret(self, server: ServerProfile) -> str | None:
        override = self._override(server)
        return (override.oslc_consumer_secret if override and override.oslc_consumer_secret else None) or self.settings.resolved_twc_oslc_consumer_secret

    def configured_consumer_credentials(self, server: ServerProfile) -> OSLCConsumerCredentials | None:
        consumer_key = self.consumer_key(server)
        consumer_secret = self.consumer_secret(server)
        if not consumer_key or not consumer_secret:
            return None
        return OSLCConsumerCredentials(consumer_key=consumer_key, consumer_secret=consumer_secret, source="config")

    def effective_consumer_credentials(
        self,
        server: ServerProfile,
        shared_credentials: OSLCConsumerCredentials | None = None,
        session_credentials: OSLCConsumerCredentials | None = None,
    ) -> OSLCConsumerCredentials | None:
        if session_credentials and session_credentials.consumer_key and session_credentials.consumer_secret:
            return session_credentials
        if shared_credentials and shared_credentials.consumer_key and shared_credentials.consumer_secret:
            return shared_credentials
        return self.configured_consumer_credentials(server)

    def rootservices_url(self, server: ServerProfile) -> str:
        override = self._override(server)
        configured = (override.oslc_rootservices_url if override and override.oslc_rootservices_url else None) or self.settings.twc_oslc_rootservices_url
        if configured:
            if configured.startswith(("http://", "https://")):
                return configured
            return self._build_server_url(server, configured, port=(override.oslc_port if override and override.oslc_port is not None else self.settings.twc_oslc_port))

        oslc_base_path = (override.oslc_base_path if override and override.oslc_base_path else None) or self.settings.twc_oslc_base_path
        oslc_port = (override.oslc_port if override and override.oslc_port is not None else None)
        if oslc_port is None:
            oslc_port = self.settings.twc_oslc_port
        normalized_base_path = (oslc_base_path or "/oslc/api").rstrip("/")
        return self._build_server_url(server, f"{normalized_base_path}/rootservices", port=oslc_port)

    def request_url(self, rootservices_url: str, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        parsed = urlparse(rootservices_url)
        path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    def callback_url(self) -> str:
        return self.settings.resolved_twc_oslc_callback_url

    def is_configured_for_server(
        self,
        server: ServerProfile,
        shared_credentials: OSLCConsumerCredentials | None = None,
        session_credentials: OSLCConsumerCredentials | None = None,
    ) -> bool:
        return self.effective_consumer_credentials(server, shared_credentials, session_credentials) is not None

    def configuration_error(
        self,
        server: ServerProfile,
        shared_credentials: OSLCConsumerCredentials | None = None,
        session_credentials: OSLCConsumerCredentials | None = None,
    ) -> str | None:
        if self.is_configured_for_server(server, shared_credentials, session_credentials):
            return None
        return "OSLC requires an approved OAuth consumer key and consumer secret for this server, either from app config, shared admin settings, or this session."

    async def discover(self, server: ServerProfile) -> OSLCDiscoveryResult:
        rootservices_url = self.rootservices_url(server)
        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        async with httpx.AsyncClient(timeout=20.0, verify=verify, follow_redirects=True) as client:
            response = await client.get(rootservices_url, headers={"Accept": "application/rdf+xml, application/xml;q=0.9, text/xml;q=0.8"})
        if response.status_code >= 400:
            raise RuntimeError(f"OSLC root services discovery failed with HTTP {response.status_code}: {response.text[:500]}")

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            raise RuntimeError("OSLC root services discovery did not return valid XML.") from exc

        links: dict[str, str] = {}
        for element in root.iter():
            local_name = _xml_local_name(element.tag)
            if local_name not in {
                "oauthRequestTokenUrl",
                "oauthUserAuthorizationUrl",
                "oauthAccessTokenUrl",
                "oauthRequestConsumerKeyUrl",
                "serviceProviders",
                "cmServiceProviders",
            }:
                continue
            value = _xml_attr_resource(element)
            if value:
                links[local_name] = value

        summary = OSLCRootServicesSummary(
            rootservices_url=rootservices_url,
            service_provider_catalog_url=links.get("serviceProviders"),
            configuration_management_service_providers_url=links.get("cmServiceProviders"),
            request_token_url=links.get("oauthRequestTokenUrl"),
            authorize_url=links.get("oauthUserAuthorizationUrl"),
            access_token_url=links.get("oauthAccessTokenUrl"),
            request_consumer_key_url=links.get("oauthRequestConsumerKeyUrl"),
            raw_content_type=response.headers.get("content-type", ""),
        )
        return OSLCDiscoveryResult(summary=summary, rootservices_text=response.text)

    async def request_consumer_key(
        self,
        server: ServerProfile,
        summary: OSLCRootServicesSummary,
        *,
        consumer_name: str,
        consumer_secret: str,
    ) -> str:
        if not summary.request_consumer_key_url:
            raise RuntimeError("OSLC root services did not publish an OAuth consumer key registration URL.")
        request_consumer_key_url = self.request_url(summary.rootservices_url, summary.request_consumer_key_url)
        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        async with httpx.AsyncClient(timeout=20.0, verify=verify, follow_redirects=True) as client:
            response = await client.post(
                request_consumer_key_url,
                json={"name": consumer_name, "secret": consumer_secret},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        if response.status_code >= 400:
            raise PermissionError(
                f"OSLC consumer key registration failed with HTTP {response.status_code}: {response.text[:500]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PermissionError("OSLC consumer key registration did not return JSON.") from exc
        consumer_key = payload.get("key")
        if not isinstance(consumer_key, str) or not consumer_key.strip():
            raise PermissionError("OSLC consumer key registration did not return a consumer key.")
        return consumer_key.strip()

    async def request_token(
        self,
        server: ServerProfile,
        summary: OSLCRootServicesSummary,
        callback_url: str,
        *,
        consumer_credentials: OSLCConsumerCredentials | None = None,
        shared_credentials: OSLCConsumerCredentials | None = None,
    ) -> tuple[str, str]:
        resolved_credentials = self.effective_consumer_credentials(server, shared_credentials, consumer_credentials)
        if resolved_credentials is None:
            raise PermissionError("OSLC requires an approved OAuth consumer key and consumer secret.")
        if not summary.request_token_url:
            raise RuntimeError("OSLC root services did not publish an OAuth request token URL.")
        request_token_url = self.request_url(summary.rootservices_url, summary.request_token_url)

        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        headers = {
            "Authorization": _oauth_authorization_header(
                "POST",
                request_token_url,
                resolved_credentials.consumer_key,
                resolved_credentials.consumer_secret,
                callback_url=callback_url,
            ),
        }
        async with httpx.AsyncClient(timeout=20.0, verify=verify, follow_redirects=True) as client:
            response = await client.post(request_token_url, headers=headers)
        if response.status_code >= 400:
            raise PermissionError(f"OSLC request token exchange failed with HTTP {response.status_code}: {response.text[:500]}")
        payload = dict(parse_qsl(response.text, keep_blank_values=True))
        token = payload.get("oauth_token")
        token_secret = payload.get("oauth_token_secret")
        if not token or not token_secret:
            raise PermissionError("OSLC request token exchange did not return oauth_token and oauth_token_secret.")
        return token, token_secret

    def authorize_redirect_url(self, summary: OSLCRootServicesSummary, request_token: str) -> str:
        if not summary.authorize_url:
            raise RuntimeError("OSLC root services did not publish an OAuth user authorization URL.")
        authorize_url = self.request_url(summary.rootservices_url, summary.authorize_url)
        separator = "&" if "?" in authorize_url else "?"
        return f"{authorize_url}{separator}oauth_token={quote(request_token, safe='')}"

    async def access_token(
        self,
        server: ServerProfile,
        summary: OSLCRootServicesSummary,
        *,
        request_token: str,
        request_token_secret: str,
        verifier: str,
        consumer_credentials: OSLCConsumerCredentials | None = None,
        shared_credentials: OSLCConsumerCredentials | None = None,
    ) -> OSLCTokenBundle:
        resolved_credentials = self.effective_consumer_credentials(server, shared_credentials, consumer_credentials)
        if resolved_credentials is None:
            raise PermissionError("OSLC requires an approved OAuth consumer key and consumer secret.")
        if not summary.access_token_url:
            raise RuntimeError("OSLC root services did not publish an OAuth access token URL.")
        access_token_url = self.request_url(summary.rootservices_url, summary.access_token_url)

        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        headers = {
            "Authorization": _oauth_authorization_header(
                "POST",
                access_token_url,
                resolved_credentials.consumer_key,
                resolved_credentials.consumer_secret,
                token=request_token,
                token_secret=request_token_secret,
                verifier=verifier,
            ),
        }
        async with httpx.AsyncClient(timeout=20.0, verify=verify, follow_redirects=True) as client:
            response = await client.post(access_token_url, headers=headers)
        if response.status_code >= 400:
            raise PermissionError(f"OSLC access token exchange failed with HTTP {response.status_code}: {response.text[:500]}")
        payload = dict(parse_qsl(response.text, keep_blank_values=True))
        token = payload.get("oauth_token")
        token_secret = payload.get("oauth_token_secret")
        if not token or not token_secret:
            raise PermissionError("OSLC access token exchange did not return oauth_token and oauth_token_secret.")
        return OSLCTokenBundle(
            access_token=token,
            access_token_secret=token_secret,
            consumer_key=resolved_credentials.consumer_key,
            consumer_secret=resolved_credentials.consumer_secret,
            rootservices_url=summary.rootservices_url,
            request_token_url=summary.request_token_url or "",
            authorize_url=summary.authorize_url or "",
            access_token_url=summary.access_token_url or "",
            service_provider_catalog_url=summary.service_provider_catalog_url,
            request_consumer_key_url=summary.request_consumer_key_url,
            configuration_management_service_providers_url=summary.configuration_management_service_providers_url,
        )

    async def signed_request(
        self,
        server: ServerProfile,
        credentials: OSLCTokenBundle,
        *,
        method: str,
        path_or_url: str,
        accept: str | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        consumer_secret = credentials.consumer_secret or self.consumer_secret(server)
        if not consumer_secret:
            raise PermissionError("OSLC consumer secret is no longer configured for this server.")

        url = self.request_url(credentials.rootservices_url, path_or_url)
        headers = {
            "Authorization": _oauth_authorization_header(
                method,
                url,
                credentials.consumer_key,
                consumer_secret,
                token=credentials.access_token,
                token_secret=credentials.access_token_secret,
            ),
        }
        if accept:
            headers["Accept"] = accept

        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        async with httpx.AsyncClient(timeout=timeout, verify=verify, follow_redirects=True) as client:
            response = await client.request(method, url, headers=headers)
        return response

    def _build_server_url(self, server: ServerProfile, path_or_url: str, *, port: int | None = None) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        normalized_path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        parsed = urlparse(server.base_url.rstrip("/"))
        netloc = parsed.hostname or parsed.netloc
        if port is not None and parsed.hostname:
            host = parsed.hostname
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            netloc = f"{host}:{port}"
        return urlunparse((parsed.scheme or "https", netloc, normalized_path, "", "", ""))
