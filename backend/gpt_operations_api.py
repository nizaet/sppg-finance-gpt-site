"""GPT gateway for the operational screens that were not yet Action-enabled.

The browser application and a GPT must use the same domain functions.  This
router deliberately dispatches only a named allow-list; it is not a generic
HTTP proxy and cannot call login, webhooks, or arbitrary internal routes.
"""

from __future__ import annotations

from datetime import date as Date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.accountant_status_api import mark_accountant_submission_sent
from backend.calculator_planning_bridge_api import CalculatorPlanningSyncIn, sync_calculator_planning
from backend.domain_api import (
    AccountantInvoiceIn,
    AccountantSubmissionIn,
    ActualUsageBatchIn,
    BgnApprovalIn,
    BgnMakerIn,
    BgnReceiptIn,
    GoodsReceiptIn,
    SettlementIn,
    accountant_flow,
    audit_log,
    bgn_flow,
    create_accountant_invoice,
    create_accountant_submission,
    create_bgn_approval,
    create_bgn_maker,
    create_bgn_receipt,
    create_goods_receipt,
    create_settlement,
    get_actual_usage,
    list_goods_receipts,
    save_actual_usage,
)
from backend.gpt_bridge_api import require_gpt_auth
from backend.inventory_api import delete_stock_opname, stock_opname_detail, stock_opnames
from backend.operational_api import (
    PurchaseOrderCreateIn,
    create_purchase_order,
    get_purchase_order,
    list_purchase_orders,
    receiving_variance,
)
from backend.planning_api import (
    PlanningSnapshotIn,
    get_planning_snapshot,
    ingest_planning_snapshot,
    list_planning_snapshots,
)
from backend.purchase_order_workflow_api import (
    PurchaseOrderEditIn,
    VendorWhatsAppUpdateIn,
    cancel_purchase_order,
    edit_purchase_order,
    finalize_purchase_order,
    mark_purchase_order_sent,
    revise_purchase_order,
    update_vendor_whatsapp,
)
from backend.reference_api import reference_vendors
from backend.vendor_rule_admin_api import VendorLeadTimeUpdateIn, update_vendor_lead_time

router = APIRouter(prefix="/v1/gpt", tags=["gpt-operations"])


ReadResource = Literal[
    "DASHBOARD",
    "PO_CALENDAR",
    "PO_REMINDERS",
    "VENDORS",
    "PLANNING_SNAPSHOTS",
    "PURCHASE_ORDERS",
    "GOODS_RECEIPTS",
    "RECEIVING_VARIANCE",
    "STOCK_OPNAMES",
    "ACTUAL_USAGE",
    "ACCOUNTANT_FLOW",
    "BGN_FLOW",
    "VENDOR_PAYMENTS",
    "AUDIT_LOG",
]


class GptOperationReadIn(BaseModel):
    resource: ReadResource
    site: str | None = None
    date: Date | None = None
    from_date: Date | None = None
    to_date: Date | None = None
    vendor: str | None = None
    status: str | None = None
    location: str | None = None
    record_id: int | None = Field(default=None, ge=1)
    production_cycle_id: int | None = Field(default=None, ge=1)
    limit: int | None = Field(default=None, ge=1, le=500)
    horizon_days: int | None = Field(default=None, ge=1, le=31)


@router.post("/operations/read", dependencies=[Depends(require_gpt_auth)])
def read_application_operation(payload: GptOperationReadIn) -> dict[str, Any]:
    """Read operational application data through a stable GPT Action surface."""
    p = payload
    if p.resource == "DASHBOARD":
        if not p.date:
            raise HTTPException(400, "date is required for DASHBOARD")
        from backend.app import control_tower
        result = control_tower(p.date)
    elif p.resource == "PO_CALENDAR":
        if not p.from_date or not p.to_date:
            raise HTTPException(400, "from_date and to_date are required for PO_CALENDAR")
        from backend.app import po_calendar
        result = po_calendar(p.from_date, p.to_date, p.site)
    elif p.resource == "PO_REMINDERS":
        from backend.app import po_reminders
        result = po_reminders(p.site or "", p.date, p.horizon_days or 14)
    elif p.resource == "VENDORS":
        result = reference_vendors(p.site or "")
    elif p.resource == "PLANNING_SNAPSHOTS":
        result = get_planning_snapshot(p.record_id) if p.record_id else list_planning_snapshots(p.site or "", p.date, True)
    elif p.resource == "PURCHASE_ORDERS":
        result = get_purchase_order(p.record_id) if p.record_id else list_purchase_orders(
            p.site or "", p.vendor or "", p.status or "", p.limit or 100
        )
    elif p.resource == "GOODS_RECEIPTS":
        result = list_goods_receipts(p.site or "", p.limit or 100)
    elif p.resource == "RECEIVING_VARIANCE":
        result = receiving_variance(p.site or "", p.limit or 200)
    elif p.resource == "STOCK_OPNAMES":
        result = stock_opname_detail(p.record_id) if p.record_id else stock_opnames(p.location or "", p.limit or 50, False)
    elif p.resource == "ACTUAL_USAGE":
        if not p.production_cycle_id:
            raise HTTPException(400, "production_cycle_id is required for ACTUAL_USAGE")
        result = get_actual_usage(p.production_cycle_id)
    elif p.resource == "ACCOUNTANT_FLOW":
        result = accountant_flow(p.site or "")
    elif p.resource == "BGN_FLOW":
        result = bgn_flow(p.site or "")
    elif p.resource == "VENDOR_PAYMENTS":
        from backend.app import vendor_payments
        result = vendor_payments(p.status or "", p.site or "")
    elif p.resource == "AUDIT_LOG":
        result = audit_log(p.limit or 200)
    else:  # Defensive guard for future enum changes.
        raise HTTPException(400, "unsupported resource")
    return {"resource": p.resource, "result": result}


WriteOperation = Literal[
    "CREATE_PLANNING_SNAPSHOT",
    "CREATE_PURCHASE_ORDER",
    "EDIT_DRAFT_PURCHASE_ORDER",
    "REVISE_PURCHASE_ORDER",
    "CANCEL_PURCHASE_ORDER",
    "FINALIZE_PURCHASE_ORDER",
    "MARK_PURCHASE_ORDER_SENT",
    "RECORD_GOODS_RECEIPT_MANUAL",
    "RECORD_ACTUAL_USAGE",
    "SYNC_CALCULATOR_PLANNING",
    "SET_VENDOR_WHATSAPP",
    "SET_VENDOR_LEAD_TIME",
    "REVIEW_EVENT",
    "VOID_STOCK_OPNAME",
    "CREATE_ACCOUNTANT_SUBMISSION",
    "MARK_ACCOUNTANT_SUBMISSION_SENT",
    "CREATE_ACCOUNTANT_INVOICE",
    "CREATE_BGN_MAKER",
    "CREATE_BGN_APPROVAL",
    "CREATE_BGN_RECEIPT",
    "CREATE_SETTLEMENT",
]


class GptOperationWriteIn(BaseModel):
    operation: WriteOperation
    payload: dict[str, Any] = Field(default_factory=dict)
    commit: bool = False


class PurchaseOrderCommandIn(BaseModel):
    purchase_order_id: int = Field(ge=1)


class PurchaseOrderEditCommandIn(PurchaseOrderEditIn):
    purchase_order_id: int = Field(ge=1)


class StockOpnameVoidCommandIn(BaseModel):
    stock_opname_id: int = Field(ge=1)
    reason: str = ""


class ReviewEventCommandIn(BaseModel):
    event_id: int = Field(ge=1)
    decision: Literal["APPROVE", "REJECT"]
    note: str = ""
    actor: str = "chatgpt"


class VendorWhatsAppCommandIn(BaseModel):
    vendor_code: str = Field(min_length=1)
    whatsapp_phone: str = Field(min_length=1)


class AccountantSubmissionCommandIn(BaseModel):
    submission_id: int = Field(ge=1)


def _preview(operation: str, model: BaseModel) -> dict[str, Any]:
    """Validate first without creating a second, divergent preview business flow."""
    return {
        "committed": False,
        "canCommit": True,
        "operation": operation,
        "normalizedPayload": model.model_dump(mode="json", exclude_none=True),
        "message": "Validated preview. No application record was changed.",
    }


@router.post("/operations/execute", dependencies=[Depends(require_gpt_auth)])
def preview_or_execute_application_operation(payload: GptOperationWriteIn) -> dict[str, Any]:
    """Validate/commit allowed application operations from GPT with one commit gate."""
    data = payload.payload
    operation = payload.operation

    model_types: dict[str, type[BaseModel]] = {
        "CREATE_PLANNING_SNAPSHOT": PlanningSnapshotIn,
        "CREATE_PURCHASE_ORDER": PurchaseOrderCreateIn,
        "EDIT_DRAFT_PURCHASE_ORDER": PurchaseOrderEditCommandIn,
        "REVISE_PURCHASE_ORDER": PurchaseOrderCommandIn,
        "CANCEL_PURCHASE_ORDER": PurchaseOrderCommandIn,
        "FINALIZE_PURCHASE_ORDER": PurchaseOrderCommandIn,
        "MARK_PURCHASE_ORDER_SENT": PurchaseOrderCommandIn,
        "RECORD_GOODS_RECEIPT_MANUAL": GoodsReceiptIn,
        "RECORD_ACTUAL_USAGE": ActualUsageBatchIn,
        "SYNC_CALCULATOR_PLANNING": CalculatorPlanningSyncIn,
        "SET_VENDOR_WHATSAPP": VendorWhatsAppCommandIn,
        "SET_VENDOR_LEAD_TIME": VendorLeadTimeUpdateIn,
        "REVIEW_EVENT": ReviewEventCommandIn,
        "VOID_STOCK_OPNAME": StockOpnameVoidCommandIn,
        "CREATE_ACCOUNTANT_SUBMISSION": AccountantSubmissionIn,
        "MARK_ACCOUNTANT_SUBMISSION_SENT": AccountantSubmissionCommandIn,
        "CREATE_ACCOUNTANT_INVOICE": AccountantInvoiceIn,
        "CREATE_BGN_MAKER": BgnMakerIn,
        "CREATE_BGN_APPROVAL": BgnApprovalIn,
        "CREATE_BGN_RECEIPT": BgnReceiptIn,
        "CREATE_SETTLEMENT": SettlementIn,
    }
    model_type = model_types.get(operation)
    validated = model_type.model_validate(data) if model_type else None
    if not payload.commit:
        if validated:
            return _preview(operation, validated)
        return {
            "committed": False,
            "canCommit": True,
            "operation": operation,
            "normalizedPayload": data,
            "message": "Validated command preview. No application record was changed.",
        }

    if operation == "CREATE_PLANNING_SNAPSHOT":
        result = ingest_planning_snapshot(validated)  # type: ignore[arg-type]
    elif operation == "CREATE_PURCHASE_ORDER":
        result = create_purchase_order(validated)  # type: ignore[arg-type]
    elif operation == "EDIT_DRAFT_PURCHASE_ORDER":
        result = edit_purchase_order(validated.purchase_order_id, validated)  # type: ignore[union-attr]
    elif operation == "REVISE_PURCHASE_ORDER":
        result = revise_purchase_order(validated.purchase_order_id)  # type: ignore[union-attr]
    elif operation == "CANCEL_PURCHASE_ORDER":
        result = cancel_purchase_order(validated.purchase_order_id)  # type: ignore[union-attr]
    elif operation == "FINALIZE_PURCHASE_ORDER":
        result = finalize_purchase_order(validated.purchase_order_id)  # type: ignore[union-attr]
    elif operation == "MARK_PURCHASE_ORDER_SENT":
        result = mark_purchase_order_sent(validated.purchase_order_id)  # type: ignore[union-attr]
    elif operation == "RECORD_GOODS_RECEIPT_MANUAL":
        result = create_goods_receipt(validated)  # type: ignore[arg-type]
    elif operation == "RECORD_ACTUAL_USAGE":
        result = save_actual_usage(validated)  # type: ignore[arg-type]
    elif operation == "SYNC_CALCULATOR_PLANNING":
        result = sync_calculator_planning(validated)  # type: ignore[arg-type]
    elif operation == "SET_VENDOR_WHATSAPP":
        result = update_vendor_whatsapp(
            validated.vendor_code,  # type: ignore[union-attr]
            VendorWhatsAppUpdateIn(whatsapp_phone=validated.whatsapp_phone),  # type: ignore[union-attr]
        )
    elif operation == "SET_VENDOR_LEAD_TIME":
        result = update_vendor_lead_time(validated)  # type: ignore[arg-type]
    elif operation == "REVIEW_EVENT":
        from backend.app import ReviewDecision, review_decision
        result = review_decision(
            validated.event_id,  # type: ignore[union-attr]
            ReviewDecision(
                decision=validated.decision, note=validated.note, actor=validated.actor  # type: ignore[union-attr]
            ),
        )
    elif operation == "VOID_STOCK_OPNAME":
        result = delete_stock_opname(validated.stock_opname_id, validated.reason)  # type: ignore[union-attr]
    elif operation == "CREATE_ACCOUNTANT_SUBMISSION":
        result = create_accountant_submission(validated)  # type: ignore[arg-type]
    elif operation == "MARK_ACCOUNTANT_SUBMISSION_SENT":
        result = mark_accountant_submission_sent(validated.submission_id)  # type: ignore[union-attr]
    elif operation == "CREATE_ACCOUNTANT_INVOICE":
        result = create_accountant_invoice(validated)  # type: ignore[arg-type]
    elif operation == "CREATE_BGN_MAKER":
        result = create_bgn_maker(validated)  # type: ignore[arg-type]
    elif operation == "CREATE_BGN_APPROVAL":
        result = create_bgn_approval(validated)  # type: ignore[arg-type]
    elif operation == "CREATE_BGN_RECEIPT":
        result = create_bgn_receipt(validated)  # type: ignore[arg-type]
    elif operation == "CREATE_SETTLEMENT":
        result = create_settlement(validated)  # type: ignore[arg-type]
    else:
        raise HTTPException(400, "unsupported operation")
    return {"committed": True, "operation": operation, "result": result}
