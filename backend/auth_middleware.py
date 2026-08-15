from __future__ import annotations

import hmac
import json
import os
from urllib.parse import parse_qsl, urlencode

from starlette.responses import JSONResponse

from backend.auth_api import auth_config, verify_session


PUBLIC_PREFIXES = (
    "/v1/auth/",
    "/v1/firebase/",
    "/v1/gpt/",
    "/v1/whatsapp/",
    "/v1/schema/",
    "/docs",
    "/redoc",
    "/openapi.json",
)
PUBLIC_EXACT = {"/health", "/v1/auth/config", "/v1/auth/login", "/v1/auth/logout"}


def _authorization(headers: list[tuple[bytes, bytes]]) -> str:
    for key, value in headers:
        if key.lower() == b"authorization":
            return value.decode("latin-1").strip()
    return ""


def _bearer(value: str) -> str:
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _role_from_auth(value: str) -> str | None:
    token = _bearer(value)
    if not token:
        return None
    gpt_key = os.getenv("SPPG_GPT_API_KEY", "").strip()
    if gpt_key and hmac.compare_digest(token, gpt_key):
        return "OWNER"
    try:
        return str(verify_session(token).get("role") or "").upper() or None
    except Exception:
        return None


# Kept for regression compatibility and utility tests. They no longer grant site
# roles operational API access; the middleware below blocks those roles entirely.
def _query_with_site(scope: dict, role: str) -> tuple[bool, str | None]:
    pairs = parse_qsl(scope.get("query_string", b"").decode("utf-8"), keep_blank_values=True)
    values = [v for k, v in pairs if k.lower() == "site" and v]
    if values and any(v.upper() != role for v in values):
        return False, "akun hanya dapat mengakses site sendiri"
    if not values:
        pairs.append(("site", role))
        scope["query_string"] = urlencode(pairs).encode("utf-8")
    return True, None


def _validate_body_site(body: bytes, role: str) -> tuple[bool, str | None]:
    if not body:
        return False, "site wajib ada untuk akun dapur"
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return False, "payload JSON tidak valid"
    if not isinstance(payload, dict):
        return False, "payload harus berupa object"
    site = str(payload.get("site") or "").upper().strip()
    if not site:
        return False, "site wajib ada untuk akun dapur"
    if site != role:
        return False, "akun hanya dapat menulis ke site sendiri"
    return True, None


def _json_response(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code)


class SppgAccessMiddleware:
    """Final role policy.

    OWNER: both calculators + Operational Control Center + accountant modules.
    MAJA: calculator MAJA only.
    CEMPLANG: calculator CEMPLANG only.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")

        if method == "OPTIONS" or not auth_config().get("enabled"):
            await self.app(scope, receive, send)
            return

        if path in PUBLIC_EXACT or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return

        if not path.startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        role = _role_from_auth(_authorization(scope.get("headers") or []))
        if role not in {"OWNER", "MAJA", "CEMPLANG"}:
            response = _json_response(401, "SPPG login required")
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})["sppg_role"] = role
        if role == "OWNER":
            await self.app(scope, receive, send)
            return

        response = _json_response(403, f"akun {role} hanya dapat menggunakan Kalkulator {role}")
        await response(scope, receive, send)
