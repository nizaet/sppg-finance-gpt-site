from __future__ import annotations

import hashlib
import uuid
from typing import Any

from mcp.types import ToolAnnotations

from plugin_mcp.core_proxy import (
    blocked_write,
    core_request,
    operational_writes_enabled,
    preview_only,
)


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
NONDESTRUCTIVE_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def _clean_site(site: str | None) -> str | None:
    if site is None or str(site).strip() == "":
        return None
    value = str(site).strip().upper()
    if value not in {"MAJA", "CEMPLANG"}:
        raise ValueError("site must be MAJA or CEMPLANG")
    return value


def _memory_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "memoryMutation": True,
        "operationalMutation": False,
    }


def _preview_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "mcpPreviewOnly": True,
        "operationalMutation": False,
    }


async def parseOnlySuppliedSppgVendorInvoiceText(
    site: str,
    vendor_code: str,
    invoice_date_label: str,
    text: str,
) -> dict[str, Any]:
    """Parse only the exact vendor invoice text supplied in this call."""
    return _preview_result(await core_request(
        "POST", "/v1/vendor-invoices/parse-whatsapp",
        json_body={
            "site": _clean_site(site),
            "vendor_code": vendor_code,
            "invoice_date_label": invoice_date_label,
            "text": text,
        },
    ))


async def searchSppgPurchaseOrdersForReconciliation(
    site: str | None = None,
    vendor: str | None = None,
    distributionDate: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find real purchase orders before reconciliation. Never invent a PO id."""
    return await core_request("GET", "/v1/purchase-orders/search", params={
        "site": _clean_site(site), "vendor": vendor, "distributionDate": distributionDate,
        "status": status, "limit": limit,
    })


async def searchSppgGoodsReceiptsForReconciliation(
    site: str | None = None,
    vendor: str | None = None,
    purchaseOrderId: int | None = None,
    distributionDate: str | None = None,
    receivedDate: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find actual goods receipts before payable reconciliation."""
    return await core_request("GET", "/v1/goods-receipts/search", params={
        "site": _clean_site(site), "vendor": vendor, "purchaseOrderId": purchaseOrderId,
        "distributionDate": distributionDate, "receivedDate": receivedDate, "limit": limit,
    })


async def processSppgVendorPayableFromReceipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview a reconciled vendor payable. This MCP phase forces commit=false."""
    body = preview_only(payload)
    if "site" in body:
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request("POST", "/v1/vendor-payables/from-receipt", json_body=body))


async def searchSppgVendorPayables(
    site: str | None = None,
    vendor: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Search already-recorded vendor payables."""
    return await core_request("GET", "/v1/vendor-payables", params={
        "site": _clean_site(site), "vendor": vendor, "status": status, "limit": limit,
    })


async def confirmSppgVendorPayment(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview vendor payment reconciliation. This MCP phase forces commit=false."""
    return _preview_result(await core_request(
        "POST", "/v1/vendor-payments/confirm", json_body=preview_only(payload)
    ))


async def postSppgReceiptToInventory(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview posting a confirmed receipt into inventory. Forces commit=false."""
    body = preview_only(payload)
    if "site" in body:
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request("POST", "/v1/inventory/from-receipt", json_body=body))


async def processSppgInventoryUsage(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview actual inventory usage. Forces commit=false."""
    body = preview_only(payload)
    if "site" in body:
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request("POST", "/v1/inventory/usage", json_body=body))


async def getSppgInventoryBalance(site: str, item: str) -> dict[str, Any]:
    """Read current inventory balance for one item."""
    return await core_request("GET", "/v1/inventory/balance", params={
        "site": _clean_site(site), "item": item,
    })


async def previewSppgInventoryRequirement(
    site: str,
    item: str,
    plannedQty: float,
    unit: str = "kg",
) -> dict[str, Any]:
    """Preview purchase need after current stock."""
    return await core_request("GET", "/v1/inventory/requirement-preview", params={
        "site": _clean_site(site), "item": item, "plannedQty": plannedQty, "unit": unit,
    })


async def previewOrRecordSppgGoodsReceiptFromMessage(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve current receiving text against live PO state. Forces commit=false."""
    body = preview_only(payload)
    if "site" in body:
        body["site"] = _clean_site(body["site"])
    result = await core_request("POST", "/v1/receiving/whatsapp", json_body=body)
    result.pop("confirmationToken", None)
    result.pop("confirmationExpiresInSeconds", None)
    return _preview_result(result)


async def stageSuppliedSppgWhatsAppActivityForReview(
    text: str,
    source_type: str = "GPT_PASTED_WHATSAPP",
    external_id: str | None = None,
    source_uri: str | None = None,
    actor: str = "chatgpt",
    context_site: str | None = None,
    context_vendor: str | None = None,
) -> dict[str, Any]:
    """Stage supplied chat/WhatsApp evidence in the review queue without mutating domain records."""
    return _memory_result(await core_request("POST", "/v1/parse-message", json_body={
        "text": text,
        "source_type": source_type,
        "external_id": external_id,
        "source_uri": source_uri,
        "actor": actor,
        "context_site": _clean_site(context_site),
        "context_vendor": context_vendor,
        "stage": True,
    }))


async def listSppgPendingOperationalReviews() -> dict[str, Any]:
    """Read pending staged operational review events."""
    return await core_request("GET", "/v1/review-queue")


async def getSppgAccountantBridgeStatus() -> dict[str, Any]:
    """Read Accountant bridge readiness."""
    return await core_request("GET", "/v1/gpt/status")


async def searchSppgAccountantTransactions(
    site: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    payment_status: str | None = None,
    q: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Search Accountant transactions from the existing SPPG bridge."""
    return await core_request("GET", "/v1/gpt/finance-transactions", params={
        "site": _clean_site(site), "from": from_date, "to": to_date,
        "payment_status": payment_status, "q": q, "limit": limit,
    })


async def createSppgAccountantTransactions(payload: dict[str, Any]) -> dict[str, Any]:
    """Legacy Accountant create action. Installed but held behind the operational write gate."""
    if not operational_writes_enabled():
        return blocked_write("createSppgAccountantTransactions", payload)
    return await core_request("POST", "/v1/gpt/finance-transactions", json_body=payload)


async def updateSppgAccountantTransaction(
    transaction_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Legacy Accountant correction action. Installed but held behind the operational write gate."""
    if not operational_writes_enabled():
        return blocked_write("updateSppgAccountantTransaction", {
            "transaction_id": transaction_id, **payload,
        })
    return await core_request(
        "PATCH", f"/v1/gpt/finance-transactions/{transaction_id}", json_body=payload
    )


async def getFinalSppgPurchaseOrderWhatsAppMessage(
    purchaseOrderId: int | None = None,
    site: str | None = None,
    vendor: str | None = None,
    distributionDate: str | None = None,
) -> dict[str, Any]:
    """Read the finalized PO and canonical WhatsApp message."""
    return await core_request("GET", "/v1/po-whatsapp-preview", params={
        "purchaseOrderId": purchaseOrderId, "site": _clean_site(site),
        "vendor": vendor, "distributionDate": distributionDate,
    })


async def previewOrRecordSppgStockOpnameFromWhatsApp(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview one physical SO baseline. Forces commit=false during migration."""
    body = preview_only(payload)
    return _preview_result(await core_request(
        "POST", "/v1/inventory/stock-opname/whatsapp", json_body=body
    ))


async def readSppgWarehouseStockAndPoProjection(
    site: str,
    forDate: str | None = None,
    search: str | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    """Read actual and projected warehouse stock using the production projection engine."""
    normalized = str(site or "").strip().upper()
    if normalized not in {"KOPERASI", "MAJA", "CEMPLANG"}:
        raise ValueError("site must be KOPERASI, MAJA or CEMPLANG")
    return await core_request("GET", "/v1/inventory/balances", params={
        "site": normalized, "forDate": forDate, "search": search, "limit": limit,
    })


async def readSppgOperationalApplication(payload: dict[str, Any]) -> dict[str, Any]:
    """Read an allow-listed Operations application workspace."""
    body = dict(payload)
    if body.get("site"):
        body["site"] = _clean_site(body["site"])
    return await core_request("POST", "/v1/gpt/operations/read", json_body=body)


async def previewOrExecuteSppgOperationalApplication(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview an allow-listed application command. Forces commit=false until the write gate is activated."""
    body = dict(payload)
    body["commit"] = False
    return _preview_result(await core_request("POST", "/v1/gpt/operations/execute", json_body=body))


async def getSppgOperationalRuntimeContext(
    site: str | None = None,
    vendor: str | None = None,
    q: str = "",
    asOf: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Load canonical rules, previously learned knowledge, conversation memory and live context."""
    return await core_request("GET", "/v1/gpt/operational-context", params={
        "site": _clean_site(site), "vendor": vendor, "q": q, "asOf": asOf, "limit": limit,
    })


async def learnSppgConversationTurn(
    user_message: str,
    assistant_summary: str | None = None,
    site: str | None = None,
    vendor: str | None = None,
    facts: list[dict[str, Any]] | None = None,
    action_context: dict[str, Any] | None = None,
    conversation_ref: str | None = None,
    turn_ref: str | None = None,
    actor: str = "sppg-control-room",
) -> dict[str, Any]:
    """Persist a meaningful turn and promote only explicit/corrected/action-confirmed durable facts."""
    conv = conversation_ref or "sppg-control-room"
    turn = turn_ref or str(uuid.uuid4())
    body = {
        "conversation_ref": conv,
        "turn_ref": turn,
        "site": _clean_site(site),
        "vendor": vendor,
        "user_message": user_message,
        "assistant_summary": assistant_summary,
        "action_context": action_context or {},
        "facts": facts or [],
        "actor": actor,
    }
    return _memory_result(await core_request("POST", "/v1/gpt/learn-conversation", json_body=body))


async def recordExplicitSppgKnowledge(
    user_message: str,
    facts: list[dict[str, Any]],
    source_ref: str | None = None,
    site: str | None = None,
    vendor: str | None = None,
    actor: str = "sppg-control-room",
) -> dict[str, Any]:
    """Store operator-requested durable knowledge as confirmed SPPG knowledge."""
    if not facts:
        raise ValueError("facts must contain at least one explicit fact")
    ref = source_ref or (
        "control-room:" + hashlib.sha256(user_message.encode("utf-8")).hexdigest()[:24]
    )
    body = {
        "source_ref": ref,
        "site": _clean_site(site),
        "vendor": vendor,
        "user_message": user_message,
        "facts": facts,
        "actor": actor,
    }
    return _memory_result(await core_request("POST", "/v1/gpt/knowledge", json_body=body))


async def previewOrRecordSppgVendorPaymentEvidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview recording verified vendor transfer evidence. Forces commit=false."""
    body = preview_only(payload)
    if body.get("site"):
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request(
        "POST", "/v1/vendor-payments/record-evidence", json_body=body
    ))


async def reconcileRecordedSppgVendorPayment(
    payment_id: int,
    vendor_invoice_id: int,
    note: str = "",
    actor: str = "sppg-control-room",
) -> dict[str, Any]:
    """Preview linking one unreconciled payment to one verified invoice. Forces commit=false."""
    return _preview_result(await core_request(
        "POST", f"/v1/vendor-payments/{payment_id}/reconcile",
        json_body={
            "vendor_invoice_id": vendor_invoice_id,
            "note": note,
            "actor": actor,
            "commit": False,
        },
    ))


async def listSppgPaidUnreconciledVendorPayments(
    site: str | None = None,
    vendor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List real vendor transfers waiting for payable reconciliation."""
    return await core_request("GET", "/v1/vendor-payments/unreconciled", params={
        "site": _clean_site(site), "vendor": vendor, "limit": limit,
    })


async def confirmSppgBgnMakerApproved(
    maker_id: int,
    approved_at: str | None = None,
    note: str | None = None,
    actor: str = "sppg-control-room",
) -> dict[str, Any]:
    """Preview confirmation that a BGN Maker has already been approved."""
    return _preview_result(await core_request(
        "POST", f"/v1/bgn-makers/{maker_id}/confirm-approved",
        json_body={"commit": False, "approved_at": approved_at, "note": note, "actor": actor},
    ))


async def confirmSppgBgnMakerPaid(
    maker_id: int,
    paid_at: str | None = None,
    evidence_uri: str | None = None,
    note: str | None = None,
    actor: str = "sppg-control-room",
) -> dict[str, Any]:
    """Preview confirmation that a BGN Maker payment was received."""
    return _preview_result(await core_request(
        "POST", f"/v1/bgn-makers/{maker_id}/confirm-paid",
        json_body={
            "commit": False, "paid_at": paid_at, "evidence_uri": evidence_uri,
            "note": note, "actor": actor,
        },
    ))



async def previewOrImportSppgHistoricalOperations(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview verified historical PO/receiving reconstruction. Forces commit=false."""
    body = preview_only(payload)
    if body.get("site"):
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request(
        "POST", "/v1/operations/history/import", json_body=body
    ))


async def previewOrBackfillSppgAccountantFirestoreHistory(
    site: str,
    batch_size: int = 200,
    start_after_id: str | None = None,
    actor: str = "sppg-control-room",
) -> dict[str, Any]:
    """Dry-run the Accountant Firestore history backfill. Never imports during this phase."""
    return _preview_result(await core_request(
        "POST", "/v1/gpt/backfill-firestore",
        json_body={
            "site": _clean_site(site),
            "dry_run": True,
            "batch_size": batch_size,
            "start_after_id": start_after_id,
            "actor": actor,
        },
    ))


async def searchSppgInventoryItemMaster(search: str | None = None) -> dict[str, Any]:
    """Search canonical inventory item types and aliases."""
    return await core_request("GET", "/v1/inventory/items", params={"search": search})


async def previewOrSaveSppgInventoryItemMaster(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview a canonical inventory item or alias update. Forces commit=false."""
    return _preview_result(await core_request(
        "POST", "/v1/inventory/items", json_body=preview_only(payload)
    ))


async def previewSppgCalculatorDailyPlanImport(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview selectable calculator daily-plan restore candidates."""
    body = dict(payload)
    if body.get("site"):
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request(
        "POST", "/v1/calculator-data/plan-preview", json_body=body
    ))


async def previewOrImportSelectedSppgCalculatorData(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview calculator master/daily-plan import. Forces commit=false."""
    body = preview_only(payload)
    if body.get("site"):
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request(
        "POST", "/v1/calculator-data/import", json_body=body
    ))


async def previewOrGenerateSppgAccountantExcel(payload: dict[str, Any]) -> dict[str, Any]:
    """Preview Accountant Excel generation from planning. Forces commit=false."""
    body = preview_only(payload)
    if body.get("site"):
        body["site"] = _clean_site(body["site"])
    return _preview_result(await core_request(
        "POST", "/v1/accountant-excel/from-planning", json_body=body
    ))


LEGACY_V0186_TOOLS = [
    (parseOnlySuppliedSppgVendorInvoiceText, READ_ONLY),
    (searchSppgPurchaseOrdersForReconciliation, READ_ONLY),
    (searchSppgGoodsReceiptsForReconciliation, READ_ONLY),
    (processSppgVendorPayableFromReceipt, READ_ONLY),
    (searchSppgVendorPayables, READ_ONLY),
    (confirmSppgVendorPayment, READ_ONLY),
    (postSppgReceiptToInventory, READ_ONLY),
    (processSppgInventoryUsage, READ_ONLY),
    (getSppgInventoryBalance, READ_ONLY),
    (previewSppgInventoryRequirement, READ_ONLY),
    (previewOrRecordSppgGoodsReceiptFromMessage, READ_ONLY),
    (stageSuppliedSppgWhatsAppActivityForReview, NONDESTRUCTIVE_WRITE),
    (listSppgPendingOperationalReviews, READ_ONLY),
    (getSppgAccountantBridgeStatus, READ_ONLY),
    (searchSppgAccountantTransactions, READ_ONLY),
    (createSppgAccountantTransactions, NONDESTRUCTIVE_WRITE),
    (updateSppgAccountantTransaction, NONDESTRUCTIVE_WRITE),
    (getFinalSppgPurchaseOrderWhatsAppMessage, READ_ONLY),
    (previewOrRecordSppgStockOpnameFromWhatsApp, READ_ONLY),
    (readSppgWarehouseStockAndPoProjection, READ_ONLY),
    (readSppgOperationalApplication, READ_ONLY),
    (previewOrExecuteSppgOperationalApplication, READ_ONLY),
    (getSppgOperationalRuntimeContext, READ_ONLY),
    (learnSppgConversationTurn, NONDESTRUCTIVE_WRITE),
    (recordExplicitSppgKnowledge, NONDESTRUCTIVE_WRITE),
    (previewOrRecordSppgVendorPaymentEvidence, READ_ONLY),
    (reconcileRecordedSppgVendorPayment, READ_ONLY),
    (listSppgPaidUnreconciledVendorPayments, READ_ONLY),
    (confirmSppgBgnMakerApproved, READ_ONLY),
    (confirmSppgBgnMakerPaid, READ_ONLY),
    # MCP is not constrained by the old GPT Builder 30-operation ceiling, so also
    # expose workflows that v0.18.6 had to omit from its imported Action schema.
    (previewOrImportSppgHistoricalOperations, READ_ONLY),
    (previewOrBackfillSppgAccountantFirestoreHistory, READ_ONLY),
    (searchSppgInventoryItemMaster, READ_ONLY),
    (previewOrSaveSppgInventoryItemMaster, READ_ONLY),
    (previewSppgCalculatorDailyPlanImport, READ_ONLY),
    (previewOrImportSelectedSppgCalculatorData, READ_ONLY),
    (previewOrGenerateSppgAccountantExcel, READ_ONLY),
]


def register_v0186_tools(mcp: Any) -> list[str]:
    names: list[str] = []
    for fn, annotations in LEGACY_V0186_TOOLS:
        mcp.add_tool(
            fn,
            name=fn.__name__,
            annotations=annotations,
        )
        names.append(fn.__name__)
    return names
