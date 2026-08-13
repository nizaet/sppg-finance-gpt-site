from __future__ import annotations

import hmac
import json
import os
import re
from urllib.parse import parse_qsl, urlencode

from starlette.responses import JSONResponse

from backend.auth_api import auth_config, verify_session
from backend.db import connection, database_ready


PUBLIC_PREFIXES = (
    "/v1/auth/",
    "/v1/gpt/",          # already protected by SPPG_GPT_API_KEY
    "/v1/whatsapp/",     # webhook/ingress has its own verification/auth
    "/v1/schema/",
    "/docs",
    "/redoc",
    "/openapi.json",
)
PUBLIC_EXACT = {"/health", "/v1/auth/config", "/v1/auth/login", "/v1/auth/logout"}

SITE_QUERY_PATHS = {
    "/v1/control-tower-v2",
    "/v1/po-calendar",
    "/v1/po-schedule/preview",
    "/v1/reference/vendors",
    "/v1/purchase-orders",
    "/v1/purchase-orders/search",
    "/v1/receiving/variance",
    "/v1/vendor-payables",
    "/v1/vendor-payments",
    "/v1/inventory/balances",
    "/v1/inventory/balance",
    "/v1/goods-receipts",
    "/v1/planning-snapshots",
}

# Site roles are intentionally narrow. OWNER/GPT can continue using the full API.
SITE_ROLE_ALLOWED = {
    ("GET", "/v1/control-tower-v2"),
    ("GET", "/v1/po-calendar"),
    ("GET", "/v1/po-schedule/preview"),
    ("GET", "/v1/reference/vendors"),
    ("GET", "/v1/purchase-orders"),
    ("GET", "/v1/purchase-orders/search"),
    ("POST", "/v1/purchase-orders"),
    ("GET", "/v1/receiving/variance"),
    ("POST", "/v1/receiving/whatsapp"),
    ("GET", "/v1/goods-receipts"),
    ("GET", "/v1/inventory/balances"),
    ("GET", "/v1/inventory/balance"),
    ("GET", "/v1/vendor-payables"),
    ("GET", "/v1/vendor-payments"),
    ("POST", "/v1/vendor-invoices/parse-whatsapp"),
    ("GET", "/v1/planning-snapshots"),
}

PO_DETAIL_RE = re.compile(r"^/v1/purchase-orders/(?P<id>\d+)$")
PLANNING_DETAIL_RE = re.compile(r"^/v1/planning-snapshots/(?P<id>\d+)$")


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


def _site_from_resource(path: str) -> str | None:
    if not database_ready():
        return None
    po_match = PO_DETAIL_RE.match(path)
    planning_match = PLANNING_DETAIL_RE.match(path)
    with connection() as conn:
        with conn.cursor() as cur:
            if po_match:
                cur.execute("select site from purchase_orders where id=%s", (int(po_match.group("id")),))
                row = cur.fetchone()
                return str(row["site"]).upper() if row and row.get("site") else None
            if planning_match:
                cur.execute("select site from planning_snapshots where id=%s", (int(planning_match.group("id")),))
                row = cur.fetchone()
                return str(row["site"]).upper() if row and row.get("site") else None
    return None


def _query_with_site(scope: dict, role: str) -> tuple[bool, str | None]:
    pairs = parse_qsl(scope.get("query_string", b"").decode("utf-8"), keep_blank_values=True)
    values = [v for k, v in pairs if k.lower() == "site" and v]
    if values and any(v.upper() != role for v in values):
        return False, "akun hanya dapat mengakses site sendiri"
    if not values:
        pairs.append(("site", role))
        scope["query_string"] = urlencode(pairs).encode("utf-8")
    return True, None


async def _read_body(receive):
    chunks: list[bytes] = []
    more = True
    while more:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        more = bool(message.get("more_body", False))
    body = b"".join(chunks)

    sent = False
    async def replay():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return body, replay


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


class SppgAccessMiddleware:
    """Activate only after Railway has all SPPG login secrets.

    Before activation, the application behaves exactly as before so adding the
    code cannot accidentally lock the owner out. Once active, all non-public
    /v1 application endpoints require either a signed SPPG session or the
    existing SPPG_GPT_API_KEY. MAJA/CEMPLANG sessions are further site-scoped.
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

        # Dynamic resource details are allowed only when the stored record is from this site.
        if PO_DETAIL_RE.match(path) or PLANNING_DETAIL_RE.match(path):
            resource_site = _site_from_resource(path)
            if resource_site != role:
                response = _json_response(403, "akun hanya dapat mengakses record site sendiri")
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        if (method, path) not in SITE_ROLE_ALLOWED:
            response = _json_response(403, "fitur ini hanya tersedia untuk OWNER")
            await response(scope, receive, send)
            return

        if method == "GET" and path in SITE_QUERY_PATHS:
            ok, detail = _query_with_site(scope, role)
            if not ok:
                response = _json_response(403, detail or "site access denied")
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        if method in {"POST", "PUT", "PATCH"}:
            body, replay = await _read_body(receive)
            ok, detail = _validate_body_site(body, role)
            if not ok:
                response = _json_response(403, detail or "site access denied")
                await response(scope, replay, send)
                return
            await self.app(scope, replay, send)
            return

        await self.app(scope, receive, send)
