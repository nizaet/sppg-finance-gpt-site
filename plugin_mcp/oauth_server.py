from __future__ import annotations

import base64
import hashlib
import html
import os
import re
import time
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

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


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _key():
    raw = os.getenv("SPPG_OAUTH_PRIVATE_KEY_B64", "").strip()
    if not raw:
        raise RuntimeError("OAuth signing key missing")
    try:
        pem = base64.b64decode(raw, validate=True)
        key = serialization.load_pem_private_key(pem, password=None)
    except Exception as exc:
        raise RuntimeError("OAuth signing key is invalid") from exc
    if getattr(key, "key_size", 0) < 2048:
        raise RuntimeError("OAuth RSA signing key must be at least 2048 bits")
    return key


def jwks() -> dict:
    public_numbers = _key().public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "sppg-owner-1",
                "n": _b64(
                    public_numbers.n.to_bytes(
                        (public_numbers.n.bit_length() + 7) // 8, "big"
                    )
                ),
                "e": _b64(
                    public_numbers.e.to_bytes(
                        (public_numbers.e.bit_length() + 7) // 8, "big"
                    )
                ),
            }
        ]
    }


def metadata(issuer: str) -> dict:
    return {
        "issuer": issuer,
        "authorization_endpoint": issuer + "/authorize",
        "token_endpoint": issuer + "/token",
        "registration_endpoint": issuer + "/register",
        "jwks_uri": issuer + "/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
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


async def authorize_get(
    request: Request,
    issuer: str,
    expected_resource: str,
) -> HTMLResponse | JSONResponse:
    q = request.query_params
    client_id = str(q.get("client_id") or "")
    redirect_uri = str(q.get("redirect_uri") or "")
    resource = str(q.get("resource") or "")
    scope = str(q.get("scope") or REQUIRED_SCOPE)
    challenge = str(q.get("code_challenge") or "")

    if q.get("response_type") != "code":
        return _oauth_error("unsupported_response_type", "Only authorization code is supported.")
    if q.get("code_challenge_method") != "S256" or not _pkce_allowed(challenge):
        return _oauth_error("invalid_request", "PKCE S256 is required.")
    if not q.get("state"):
        return _oauth_error("invalid_request", "state is required.")
    if not _client_allowed(client_id, redirect_uri):
        return _oauth_error("invalid_client", "Unrecognized ChatGPT OAuth client.")
    if not _resource_allowed(resource, expected_resource):
        return _oauth_error("invalid_target", "OAuth resource does not match this MCP server.")
    if not _scope_allowed(scope):
        return _oauth_error("invalid_scope", "sppg:read scope is required.")

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
<button type="submit">Izinkan akses baca</button>
</form>
<small>Akses: MAJA + CEMPLANG, read-only.</small>""",
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

    if not state or not _client_allowed(client_id, redirect_uri):
        return _oauth_error("invalid_request", "Invalid OAuth client or state.")
    if not _resource_allowed(resource, expected_resource):
        return _oauth_error("invalid_target", "OAuth resource does not match this MCP server.")
    if not _scope_allowed(scope) or not _pkce_allowed(challenge):
        return _oauth_error("invalid_request", "Invalid scope or PKCE challenge.")

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
        return _oauth_error("access_denied", "OWNER access required.", 403)

    _prune_codes()
    code = _b64(os.urandom(32))
    _CODES[code] = {
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
    code = str(form.get("code") or "")
    record = _CODES.pop(code, None)

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
    if not verifier or _b64(hashlib.sha256(verifier.encode("ascii")).digest()) != record["challenge"]:
        return _oauth_error("invalid_grant", "PKCE verification failed.")

    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": "SPPG_OWNER",
        "aud": audience,
        "iat": now,
        "exp": now + 3600,
        "scope": REQUIRED_SCOPE,
    }
    access_token = jwt.encode(
        claims,
        _key(),
        algorithm="RS256",
        headers={"kid": "sppg-owner-1"},
    )
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": REQUIRED_SCOPE,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


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
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        },
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )
