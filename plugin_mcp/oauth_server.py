from __future__ import annotations

import asyncio
import logging
import base64
import hashlib
import html
import os
import re
import time
from urllib.parse import urlencode

import httpx
import jwt
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from plugin_mcp.oauth_refresh import create_refresh, rotate_refresh, RefreshRejected

oauth_logger = logging.getLogger('sppg_oauth')


def token_response(grant, response, reason=None):
    """Audit grant type and stable error codes only; never log form/body/tokens."""
    oauth_logger.info('oauth grant=%s status=%s reason=%s', grant, response.status_code, reason or 'OK')
    return response

_CODES: dict[str, dict] = {}
CORE = os.getenv(
    "SPPG_CORE_API_URL",
    "https://sppg-finance-gpt-site-production-5b7d.up.railway.app",
).rstrip("/")

REQUIRED_SCOPE = "sppg:read"
CHATGPT_STABLE_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
CHATGPT_CIMD_CLIENT_ID = "https://chatgpt.com/oauth/client.json"
DCR_CLIENT_ID = "sppg-chatgpt-public-v1"
PKCE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def signing_secret() -> bytes:
    """Derive a server-only HMAC key from the configured OAuth secret material.

    The Railway variable may contain a PEM key, DER base64, or another high-entropy
    secret. We never expose it; the access token is validated by this same service.
    """
    raw = os.getenv("SPPG_OAUTH_PRIVATE_KEY_B64", "").strip()
    if len(raw) < 32:
        raise RuntimeError("OAuth signing secret is missing or too short")
    return hashlib.sha256(("sppg-oauth-v1:" + raw).encode("utf-8")).digest()


def jwks() -> dict:
    # HS256 is server-internal signing; no symmetric verification key is published.
    return {"keys": []}

def issue_access_token(
    issuer: str,
    audience: str,
    *,
    subject: str = "SPPG_OWNER",
    scope: str = REQUIRED_SCOPE,
    ttl_seconds: int = 3600,
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": now,
        "exp": now + ttl_seconds,
        "scope": scope,
    }
    return jwt.encode(
        claims,
        signing_secret(),
        algorithm="HS256",
        headers={"kid": "sppg-owner-hmac-v1"},
    )


def metadata(issuer: str) -> dict:
    return {
        "issuer": issuer,
        "authorization_endpoint": issuer + "/authorize",
        "token_endpoint": issuer + "/token",
        "registration_endpoint": issuer + "/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [REQUIRED_SCOPE],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
    }


def _client_allowed(client_id: str, redirect_uri: str) -> bool:
    return (
        redirect_uri == CHATGPT_STABLE_REDIRECT
        and client_id in {CHATGPT_CIMD_CLIENT_ID, DCR_CLIENT_ID}
    )


def _resource_allowed(resource: str, expected_resource: str) -> bool:
    return bool(resource) and resource.rstrip("/") == expected_resource.rstrip("/")


def _scope_allowed(scope: str) -> bool:
    scopes = set((scope or REQUIRED_SCOPE).split())
    return REQUIRED_SCOPE in scopes


def _pkce_allowed(challenge: str) -> bool:
    return bool(PKCE_RE.fullmatch(challenge or ""))


def _prune_codes() -> None:
    cutoff = int(time.time()) - 300
    for code, record in list(_CODES.items()):
        if int(record.get("iat") or 0) < cutoff:
            _CODES.pop(code, None)


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def _authorization_error_redirect(
    redirect_uri: str,
    issuer: str,
    state: str,
    error: str,
    description: str,
) -> RedirectResponse:
    params = {
        "error": error,
        "error_description": description,
        "iss": issuer,
    }
    if state:
        params["state"] = state
    return RedirectResponse(
        redirect_uri + "?" + urlencode(params),
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )


async def authorize_get(
    request: Request,
    issuer: str,
    expected_resource: str,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    q = request.query_params
    client_id = str(q.get("client_id") or "")
    redirect_uri = str(q.get("redirect_uri") or "")
    state = str(q.get("state") or "")
    resource = str(q.get("resource") or "")
    scope = str(q.get("scope") or REQUIRED_SCOPE)
    challenge = str(q.get("code_challenge") or "")

    # Never redirect to an untrusted URI. Once client + callback are validated,
    # RFC 9207 issuer identification is included in every OAuth response.
    if not _client_allowed(client_id, redirect_uri):
        return _oauth_error("invalid_client", "Unrecognized ChatGPT OAuth client.")
    if q.get("response_type") != "code":
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "unsupported_response_type", "Only authorization code is supported.",
        )
    if q.get("code_challenge_method") != "S256" or not _pkce_allowed(challenge):
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "invalid_request", "PKCE S256 is required.",
        )
    if not state:
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "invalid_request", "state is required.",
        )
    if not _resource_allowed(resource, expected_resource):
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "invalid_target", "OAuth resource does not match this MCP server.",
        )
    if not _scope_allowed(scope):
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "invalid_scope", "sppg:read scope is required.",
        )

    hidden_names = (
        "client_id",
        "redirect_uri",
        "state",
        "code_challenge",
        "scope",
        "resource",
    )
    fields = "".join(
        f'<input type="hidden" name="{html.escape(name)}" '
        f'value="{html.escape(str(q.get(name) or ""))}">'
        for name in hidden_names
    )
    return HTMLResponse(
        f"""<!doctype html>
<meta name="viewport" content="width=device-width">
<title>SPPG Plugin Login</title>
<style>
body{{font-family:system-ui;max-width:420px;margin:10vh auto;padding:24px}}
input,button{{box-sizing:border-box;width:100%;padding:12px;margin:8px 0}}
small{{color:#555}}
</style>
<h2>SPPG Operations</h2>
<p>Masuk sebagai <b>YAYASAN / OWNER</b>.</p>
<form method="post" action="/authorize">
{fields}
<input type="password" name="password" autocomplete="current-password"
       placeholder="Password OWNER" required>
<button type="submit">Hubungkan SPPG Operations</button>
</form>
<small>Akses OWNER: MAJA + CEMPLANG. Perubahan operasional memerlukan konfirmasi.</small>""",
        headers={"Cache-Control": "no-store"},
    )


async def authorize_post(
    request: Request,
    issuer: str,
    expected_resource: str,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    form = await request.form()
    client_id = str(form.get("client_id") or "")
    redirect_uri = str(form.get("redirect_uri") or "")
    state = str(form.get("state") or "")
    resource = str(form.get("resource") or "")
    scope = str(form.get("scope") or REQUIRED_SCOPE)
    challenge = str(form.get("code_challenge") or "")

    if not _client_allowed(client_id, redirect_uri):
        return _oauth_error("invalid_client", "Unrecognized ChatGPT OAuth client.")
    if not state:
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "invalid_request", "state is required.",
        )
    if not _resource_allowed(resource, expected_resource):
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "invalid_target", "OAuth resource does not match this MCP server.",
        )
    if not _scope_allowed(scope) or not _pkce_allowed(challenge):
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "invalid_request", "Invalid scope or PKCE challenge.",
        )

    password = str(form.get("password") or "")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(
                CORE + "/v1/auth/login",
                json={"username": "OWNER", "password": password, "remember": False},
            )
    except httpx.HTTPError:
        return HTMLResponse(
            "<h3>Login SPPG sementara tidak tersedia</h3>"
            "<p>Coba lagi setelah layanan Pusat Kontrol kembali normal.</p>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    if response.status_code != 200:
        return HTMLResponse(
            "<h3>Login OWNER gagal</h3><p>Password tidak cocok. Kembali dan coba lagi.</p>",
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )

    session = response.json()
    if str(session.get("role") or "").upper() != "OWNER":
        return _authorization_error_redirect(
            redirect_uri, issuer, state,
            "access_denied", "OWNER access required.",
        )

    _prune_codes()
    code = _b64(os.urandom(32))
    code_key = hashlib.sha256(code.encode("ascii")).hexdigest()
    _CODES[code_key] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "challenge": challenge,
        "scope": REQUIRED_SCOPE,
        "resource": expected_resource,
        "iat": int(time.time()),
    }
    target = redirect_uri + "?" + urlencode(
        {"code": code, "state": state, "iss": issuer}
    )
    return RedirectResponse(
        target,
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )


async def token(
    request: Request,
    issuer: str,
    audience: str,
    expected_resource: str,
) -> JSONResponse:
    form = await request.form()
    grant=str(form.get("grant_type") or "")
    if grant=="refresh_token":
        client=str(form.get("client_id") or "")
        resource=str(form.get("resource") or expected_resource)
        scope=str(form.get("scope") or REQUIRED_SCOPE)
        if client not in {CHATGPT_CIMD_CLIENT_ID,DCR_CLIENT_ID}:
            return token_response(grant, _oauth_error("invalid_client","Unrecognized ChatGPT OAuth client."), 'INVALID_CLIENT')
        if not _resource_allowed(resource,expected_resource):
            return token_response(grant, _oauth_error("invalid_target","Refresh resource mismatch."), 'RESOURCE_MISMATCH')
        if set(scope.split())!={REQUIRED_SCOPE}:
            return token_response(grant, _oauth_error("invalid_scope","Refresh cannot expand the authorized scope."), 'SCOPE_MISMATCH')
        allowed={x.strip() for x in os.getenv("SPPG_OAUTH_ALLOWED_SUBJECTS","").split(",") if x.strip()}
        try:
            renewed=await asyncio.to_thread(rotate_refresh,str(form.get("refresh_token") or ""),client,resource,audience,REQUIRED_SCOPE,allowed)
        except ValueError as exc:
            reason = exc.code if isinstance(exc, RefreshRejected) else 'INVALID_REFRESH_SESSION'
            return token_response(grant, _oauth_error("invalid_grant","Refresh session is invalid, expired, revoked or already used."), reason)
        except Exception:
            logging.getLogger("sppg_oauth").warning("Refresh store unavailable")
            return token_response(grant, _oauth_error("temporarily_unavailable","Session renewal unavailable; retry later.",503), 'REFRESH_STORE_UNAVAILABLE')
        return token_response(grant, JSONResponse({"access_token":issue_access_token(issuer,audience,subject=renewed["subject"],scope=renewed["scope"]),"refresh_token":renewed["refresh_token"],"token_type":"Bearer","expires_in":3600,"scope":REQUIRED_SCOPE},headers={"Cache-Control":"no-store","Pragma":"no-cache"}))
    if grant!="authorization_code":
        return _oauth_error("unsupported_grant_type","Only authorization_code and refresh_token are supported.")
    code = str(form.get("code") or "")
    code_key = hashlib.sha256(code.encode("ascii")).hexdigest()
    record = _CODES.pop(code_key, None)

    if not record or int(time.time()) - int(record.get("iat") or 0) > 300:
        return _oauth_error("invalid_grant", "Authorization code is invalid or expired.")

    client_id = str(form.get("client_id") or "")
    redirect_uri = str(form.get("redirect_uri") or "")
    resource = str(form.get("resource") or "")
    verifier = str(form.get("code_verifier") or "")

    if str(form.get("grant_type") or "") != "authorization_code":
        return _oauth_error("unsupported_grant_type", "Only authorization_code is supported.")
    if (
        client_id != record["client_id"]
        or redirect_uri != record["redirect_uri"]
        or not _client_allowed(client_id, redirect_uri)
    ):
        return _oauth_error("invalid_grant", "OAuth client does not match authorization code.")
    if not _resource_allowed(resource, expected_resource) or resource.rstrip("/") != str(record["resource"]).rstrip("/"):
        return _oauth_error("invalid_target", "OAuth resource does not match authorization code.")
    if not VERIFIER_RE.fullmatch(verifier):
        return _oauth_error("invalid_grant", "PKCE verifier is invalid.")
    if _b64(hashlib.sha256(verifier.encode("ascii")).digest()) != record["challenge"]:
        return _oauth_error("invalid_grant", "PKCE verification failed.")

    try:
        refresh=await asyncio.to_thread(create_refresh,client_id,expected_resource,audience,"SPPG_OWNER",REQUIRED_SCOPE)
    except Exception:
        logging.getLogger("sppg_oauth").warning("Refresh session creation unavailable")
        return _oauth_error("temporarily_unavailable","Session creation unavailable; retry authorization.",503)
    access_token = issue_access_token(issuer, audience)
    return token_response(grant, JSONResponse(
        {
            "access_token": access_token,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": REQUIRED_SCOPE,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    ))


async def register(request: Request, issuer: str) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return _oauth_error("invalid_client_metadata", "Registration body must be JSON.")

    redirect_uris = body.get("redirect_uris") or []
    if redirect_uris != [CHATGPT_STABLE_REDIRECT]:
        return _oauth_error(
            "invalid_redirect_uri",
            "Only the stable ChatGPT OAuth callback is allowed.",
        )
    token_method = str(body.get("token_endpoint_auth_method") or "none")
    if token_method != "none":
        return _oauth_error(
            "invalid_client_metadata",
            "This public client supports token_endpoint_auth_method=none only.",
        )

    return JSONResponse(
        {
            "client_id": DCR_CLIENT_ID,
            "client_id_issued_at": int(time.time()),
            "redirect_uris": [CHATGPT_STABLE_REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


