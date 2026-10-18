from __future__ import annotations

import hmac
import logging
import os
from datetime import date, datetime
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse
from plugin_mcp.oauth_resource import settings as oauth_settings, validate_access_token, unauthorized, protected_resource_metadata
from plugin_mcp.oauth_server import metadata as oauth_metadata, jwks as oauth_jwks, signing_secret as oauth_signing_secret, issue_access_token as oauth_issue_access_token, authorize_get, authorize_post, token as oauth_token, register as oauth_register
from plugin_mcp.v0186_tools import register_v0186_tools
from plugin_mcp.core_proxy import operational_writes_enabled

from backend.hermes_receiving_preview_api import (
    HermesReceivingPreviewIn,
    preview_receiving_multi_po,
)
from backend.inventory_api import StockOpnameWhatsAppIn, stock_opname_whatsapp
from backend.po_reminder_v4_api import po_reminders_v4
from backend.vendor_payables_api import (
    VendorCostLineIn,
    VendorPayableFromReceiptIn,
    list_vendor_payables,
    vendor_payable_from_receipt,
)
from backend.vendor_workflow_api import VendorInvoiceTextIn, parse_vendor_invoice


logger = logging.getLogger("sppg_plugin_mcp")

Site = Literal["MAJA", "CEMPLANG"]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
OAUTH_SECURITY_SCHEMES = [{"type": "oauth2", "scopes": ["sppg:read"]}]


class OpenAIFastMCP(FastMCP):
    """FastMCP v1.28 adapter for OpenAI's top-level tool securitySchemes extension."""

    async def list_tools(self):
        tools = await super().list_tools()
        return [
            tool.model_copy(update={"securitySchemes": OAUTH_SECURITY_SCHEMES})
            for tool in tools
        ]


mcp = OpenAIFastMCP(
    "SPPG Operations v0.18.6 Parity",
    instructions=(
        "MCP bridge for the legacy SPPG GPTS v0.18.6 workflow across MAJA and CEMPLANG. "
        "It exposes the original Action names plus focused read-only helpers. "
        "Existing confirmed SPPG knowledge and conversation memory are loaded from SPPG Core. "
        "Meaningful turns and explicit operator corrections may be written to the memory/knowledge layer. "
        "Production operational writes remain gated; preview-capable operations force commit=false until "
        "the confirmation-gated write rollout is explicitly enabled."
    ),
    host="0.0.0.0",
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
)


LEGACY_V0186_TOOL_NAMES = register_v0186_tools(mcp)


def _site(value: str) -> Site:
    normalized = str(value or "").upper().strip()
    if normalized not in {"MAJA", "CEMPLANG"}:
        raise ValueError("site must be MAJA or CEMPLANG")
    return normalized  # type: ignore[return-value]


def _date(value: str | None) -> date | None:
    text = str(value or "").strip()
    return date.fromisoformat(text) if text else None


def _datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    return datetime.fromisoformat(text) if text else None


def _safe(result: Any) -> Any:
    return jsonable_encoder(result)


@mcp.tool(annotations=READ_ONLY)
def po_action_queue(
    site: str,
    date_iso: str | None = None,
    horizon_days: int = 2,
) -> dict[str, Any]:
    """Read the same PO reminder/action engine used by the SPPG application.

    Returns requirement/coverage stages and recommended shortage quantities.
    It does not create, edit, finalize, revise, or send a PO.
    """
    if horizon_days < 1 or horizon_days > 31:
        raise ValueError("horizon_days must be between 1 and 31")
    result = po_reminders_v4(
        site=_site(site),
        as_of=_date(date_iso),
        horizon_days=horizon_days,
    )
    return _safe({**result, "mcpReadOnly": True, "operationalMutation": False})


@mcp.tool(annotations=READ_ONLY)
def receiving_preview(
    site: str,
    text: str,
    vendor_code: str | None = None,
    purchase_order_id: int | None = None,
    received_at_iso: str | None = None,
    reporter: str | None = None,
) -> dict[str, Any]:
    """Reconcile pasted/forwarded goods-arrival text against live PO state without writing.

    Uses the production multi-PO receiving resolver. Ambiguous matches, partial receipts,
    rejects and over-receipt remain visible for operator review.
    """
    if not str(text or "").strip():
        raise ValueError("text is required")
    payload = HermesReceivingPreviewIn(
        site=_site(site),
        text=text,
        vendor_code=(vendor_code or None),
        purchase_order_id=purchase_order_id,
        received_at=_datetime(received_at_iso),
        reporter=reporter,
    )
    result = preview_receiving_multi_po(payload, None)
    # Read-only MCP deliberately does not expose a write-capable confirmation token.
    result.pop("confirmationToken", None)
    result.pop("confirmationExpiresInSeconds", None)
    return _safe({
        **result,
        "committed": False,
        "mcpReadOnly": True,
        "operationalMutation": False,
    })


@mcp.tool(annotations=READ_ONLY)
def stock_opname_preview(
    site: str,
    text: str,
    stock_date_iso: str | None = None,
    reporter: str | None = None,
) -> dict[str, Any]:
    """Parse and normalize a pasted stock-opname report using the application's live master/aliases.

    Returns canonical item names, units, mapping confidence, warnings, ambiguous items and
    review-required rows. It never saves the stock opname.
    """
    if not str(text or "").strip():
        raise ValueError("text is required")
    payload = StockOpnameWhatsAppIn(
        location=_site(site),
        text=text,
        stock_date=_date(stock_date_iso),
        reporter=reporter,
        actor="plugin_read_only",
        commit=False,
    )
    result = stock_opname_whatsapp(payload)
    return _safe({
        **result,
        "committed": False,
        "mcpReadOnly": True,
        "operationalMutation": False,
    })


@mcp.tool(annotations=READ_ONLY)
def vendor_invoice_parse_preview(
    site: str,
    vendor_code: str,
    invoice_date_label: str,
    text: str,
) -> dict[str, Any]:
    """Parse ONLY the vendor invoice text supplied in this tool call.

    Does not search historical transactions as a substitute for the supplied invoice and
    does not create a payable. Useful for Holil/Wikian text before reconciliation.
    """
    if not str(text or "").strip():
        raise ValueError("text is required")
    payload = VendorInvoiceTextIn(
        site=_site(site),
        vendor_code=str(vendor_code or "").upper().strip(),
        invoice_date_label=invoice_date_label,
        text=text,
    )
    result = parse_vendor_invoice(payload)
    return _safe({
        **result,
        "mcpReadOnly": True,
        "operationalMutation": False,
    })


@mcp.tool(annotations=READ_ONLY)
def vendor_payable_preview(
    site: str,
    purchase_order_id: int,
    goods_receipt_id: int,
    lines: list[dict[str, Any]],
    invoice_number: str | None = None,
    invoice_date_iso: str | None = None,
    due_date_iso: str | None = None,
) -> dict[str, Any]:
    """Preview payable against an existing PO + goods receipt, including reject deduction.

    Each line accepts the same fields as the application:
    goods_receipt_item_id or item_name, vendor_cost_price, optional invoiced_qty,
    and optional rejected_qty. The tool forces commit=False.
    """
    validated_lines = [VendorCostLineIn(**line) for line in lines]
    payload = VendorPayableFromReceiptIn(
        site=_site(site),
        purchase_order_id=purchase_order_id,
        goods_receipt_id=goods_receipt_id,
        invoice_number=invoice_number,
        invoice_date=_date(invoice_date_iso),
        due_date=_date(due_date_iso),
        lines=validated_lines,
        commit=False,
    )
    result = vendor_payable_from_receipt(payload)
    return _safe({
        **result,
        "committed": False,
        "mcpReadOnly": True,
        "operationalMutation": False,
    })


@mcp.tool(annotations=READ_ONLY)
def vendor_payables_list(
    site: str,
    vendor: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List already-recorded vendor payables. This is not an invoice parser."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    result = list_vendor_payables(
        site=_site(site),
        vendor=str(vendor or ""),
        status=str(status or ""),
        limit=limit,
    )
    return _safe({**result, "mcpReadOnly": True, "operationalMutation": False})


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    try:
        issuer, audience, jwks_url, resource, required_scope, allowed_subjects = oauth_settings()
        oauth_signing_secret()
        if audience.rstrip("/") != resource.rstrip("/"):
            raise RuntimeError("OAuth audience must equal MCP resource")
        if "SPPG_OWNER" not in allowed_subjects:
            raise RuntimeError("SPPG_OWNER must be allowlisted")
        if required_scope != "sppg:read":
            raise RuntimeError("OAuth scope must be sppg:read")
        probe_token = oauth_issue_access_token(issuer, audience, ttl_seconds=60)
        probe_claims = validate_access_token(probe_token)
        if probe_claims.get("sub") != "SPPG_OWNER":
            raise RuntimeError("OAuth token round-trip subject mismatch")
    except Exception as exc:
        logger.warning("OAuth readiness failed: %s", exc)
        return JSONResponse(
            {
                "status": "not_ready",
                "service": "sppg-plugin-mcp",
                "mode": "read-only",
                "oauthReady": False,
                "reason": str(exc)[:200],
            },
            status_code=503,
        )

    return JSONResponse({
        "status": "ok",
        "service": "sppg-plugin-mcp",
        "mode": "v0186-parity-operational-preview",
        "oauthReady": True,
        "legacyV0186Parity": True,
        "legacyV0186ActionCount": 30,
        "parityPlusToolCount": len(LEGACY_V0186_TOOL_NAMES),
        "operationalWritesEnabled": operational_writes_enabled(),
        "knowledgeLearningEnabled": True,
        "tools": [
            "po_action_queue",
            "receiving_preview",
            "stock_opname_preview",
            "vendor_invoice_parse_preview",
            "vendor_payable_preview",
            "vendor_payables_list",
            *LEGACY_V0186_TOOL_NAMES,
        ],
    })


class BearerGate:
    """Raw ASGI bearer gate. Keeps /health public for Railway liveness checks."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path == "/health":
            await self.app(scope, receive, send)
            return

        try:
            issuer, audience, jwks_url, resource, required_scope, allowed_subjects = oauth_settings()
        except RuntimeError:
            response = JSONResponse({"detail": "OAuth not configured"}, status_code=503)
            await response(scope, receive, send)
            return

        if path == "/.well-known/oauth-authorization-server":
            response = JSONResponse(oauth_metadata(issuer))
            await response(scope, receive, send)
            return
        if path == "/.well-known/openid-configuration":
            response = JSONResponse({"detail": "OpenID Connect is not enabled"}, status_code=404)
            await response(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if path == "/jwks.json":
            response = JSONResponse(oauth_jwks())
            await response(scope, receive, send)
            return
        if path == "/register" and str(scope.get("method") or "").upper() == "POST":
            response = await oauth_register(request, issuer)
            await response(scope, receive, send)
            return
        if path == "/authorize":
            response = await (
                authorize_post(request, issuer, resource)
                if str(scope.get("method") or "").upper() == "POST"
                else authorize_get(request, issuer, resource)
            )
            await response(scope, receive, send)
            return
        if path == "/token" and str(scope.get("method") or "").upper() == "POST":
            response = await oauth_token(request, issuer, audience, resource)
            await response(scope, receive, send)
            return

        if path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            response = JSONResponse(protected_resource_metadata(resource, issuer, required_scope))
            await response(scope, receive, send)
            return

        authorization = ""
        for key, value in scope.get("headers") or []:
            if key.lower() == b"authorization":
                authorization = value.decode("latin-1").strip()
                break
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        try:
            if not supplied:
                raise ValueError("Missing token")
            validate_access_token(supplied)
        except Exception:
            response = unauthorized(resource, required_scope)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def build_app() -> Any:
    inner = mcp.streamable_http_app()
    return BearerGate(inner)


app = build_app()
