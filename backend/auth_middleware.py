from __future__ import annotations

import hmac
import os

from starlette.responses import JSONResponse

from backend.auth_api import auth_config, verify_session


PUBLIC_PREFIXES = (
    "/v1/auth/",
    "/v1/gpt/",          # protected by SPPG_GPT_API_KEY in its own router
    "/v1/whatsapp/",     # webhook/ingress has its own verification/auth
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


def _json_response(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code)


class SppgAccessMiddleware:
    """Role enforcement for the deployed SPPG application.

    Final policy:
    - OWNER: calculators, Operational Control Center, all accountant modules/API.
    - MAJA: calculator MAJA only.
    - CEMPLANG: calculator CEMPLANG only.

    Site accounts therefore cannot call operational/accountant `/v1/*` endpoints
    even if they manually type a URL. Their calculator destinations are supplied
    from auth config and live outside these protected operational endpoints.
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

        # Browser SPA assets/pages are handled by the frontend gate. API access is
        # additionally enforced here so hidden/manual URLs cannot bypass roles.
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
