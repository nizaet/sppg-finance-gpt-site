from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from backend.db import connection, database_ready
from backend.gpt_bridge_api import require_gpt_auth

router = APIRouter(prefix="/gpt", tags=["gpt-knowledge-runtime"])
RULES_PATH = Path(__file__).resolve().parent / "knowledge" / "runtime_rules_v1.json"
JAKARTA = ZoneInfo("Asia/Jakarta")


def _rules() -> dict[str, Any]:
    try:
        value = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"version": "unavailable", "loadError": f"{type(exc).__name__}: {exc}"[:1000], "decisionPolicy": [], "canonicalFacts": {}}


def _safe_query(sql: str, params: list[Any] | tuple[Any, ...]) -> dict[str, Any]:
    if not database_ready():
        return {"items": [], "error": "database unavailable"}
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return {"items": [dict(row) for row in cur.fetchall()], "error": None}
    except Exception as exc:
        return {"items": [], "error": f"{type(exc).__name__}: {exc}"[:1500]}


def _vendor_rules(site: str | None, vendor: str | None, as_of: date, limit: int) -> dict[str, Any]:
    sql = """
        select vr.id,vr.vendor_code,e.name as vendor_name,vr.site_code,vr.category_code,
               vr.lead_time_days_before_cooking,vr.payment_term_code,vr.payment_term_payload,
               vr.internal_reimbursement,vr.intermediary_code,vr.effective_from,vr.effective_to,vr.evidence_ref,vr.notes
        from vendor_rules vr left join entities e on e.code=vr.vendor_code
        where vr.effective_from<=%s and (vr.effective_to is null or vr.effective_to>=%s)
    """
    params: list[Any] = [as_of, as_of]
    if site:
        sql += " and (vr.site_code is null or upper(vr.site_code)=upper(%s))"
        params.append(site)
    if vendor:
        sql += " and upper(vr.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by vr.vendor_code,vr.site_code nulls first,vr.category_code nulls first,vr.effective_from desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _open_pos(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select po.id as purchase_order_id,po.po_code,po.revision_no,po.site,po.vendor_code,po.status,
               po.sent_at,po.created_at,pc.distribution_date,pc.cooking_at,
               poi.id as purchase_order_item_id,poi.item_code,poi.item_name,poi.po_qty,poi.unit,
               coalesce((select sum(coalesce(gri.accepted_qty,gri.received_qty,0))
                         from goods_receipt_items gri where gri.purchase_order_item_id=poi.id),0) as received_qty,
               greatest(coalesce(poi.po_qty,0)-coalesce((select sum(coalesce(gri2.accepted_qty,gri2.received_qty,0))
                         from goods_receipt_items gri2 where gri2.purchase_order_item_id=poi.id),0),0) as outstanding_qty
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        join purchase_order_items poi on poi.purchase_order_id=po.id
        where upper(po.status) in ('DRAFT','FINALIZED','SENT','ACKNOWLEDGED','PARTIAL_RECEIVED')
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by pc.distribution_date desc nulls last,po.created_at desc,po.id desc,poi.id limit %s"
    params.append(max(limit * 20, limit))
    raw = _safe_query(sql, params)
    if raw.get("error"):
        return raw
    grouped: dict[int, dict[str, Any]] = {}
    for row in raw["items"]:
        po_id = int(row["purchase_order_id"])
        po = grouped.setdefault(po_id, {
            "purchaseOrderId": po_id, "poCode": row.get("po_code"), "revisionNo": row.get("revision_no"),
            "site": row.get("site"), "vendorCode": row.get("vendor_code"), "status": row.get("status"),
            "distributionDate": row.get("distribution_date"), "cookingAt": row.get("cooking_at"),
            "sentAt": row.get("sent_at"), "createdAt": row.get("created_at"), "items": [],
        })
        po["items"].append({
            "purchaseOrderItemId": row.get("purchase_order_item_id"), "itemCode": row.get("item_code"),
            "itemName": row.get("item_name"), "poQty": row.get("po_qty"), "receivedQty": row.get("received_qty"),
            "outstandingQty": row.get("outstanding_qty"), "unit": row.get("unit"),
        })
    return {"items": list(grouped.values())[:limit], "error": None}


def _recent_receipts(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select gr.id as goods_receipt_id,gr.purchase_order_id,gr.received_at,gr.reporter,gr.match_status,gr.match_confidence,
               po.po_code,po.site,po.vendor_code,pc.distribution_date,count(gri.id) as item_count,
               coalesce(sum(coalesce(gri.accepted_qty,gri.received_qty,0)),0) as accepted_qty_total
        from goods_receipts gr join purchase_orders po on po.id=gr.purchase_order_id
        left join production_cycles pc on pc.id=po.production_cycle_id
        left join goods_receipt_items gri on gri.goods_receipt_id=gr.id where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " group by gr.id,po.id,pc.id order by gr.received_at desc nulls last,gr.id desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _payables(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select vi.id as vendor_invoice_id,vi.vendor_code,vi.site,vi.purchase_order_id,vi.goods_receipt_id,
               vi.invoice_number,vi.invoice_date,vi.net_amount,vi.payable_status,vi.due_date,vi.created_at,po.po_code
        from vendor_invoices vi left join purchase_orders po on po.id=vi.purchase_order_id
        where upper(coalesce(vi.payable_status,'UNPAID')) not in ('PAID','SETTLED')
    """
    params: list[Any] = []
    if site:
        sql += " and upper(vi.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(vi.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by vi.created_at desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _payments(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select vp.id as vendor_payment_id,vp.vendor_invoice_id,vp.vendor_code,vp.site,vp.amount,vp.payment_status,
               vp.payment_source,vp.paid_at,vp.evidence_uri,vp.reference_number,vp.candidate_purchase_order_id,
               vp.candidate_goods_receipt_id,vp.candidate_vendor_invoice_id,vp.reconciliation_note,vp.reconciled_at,vp.created_at
        from vendor_payments vp where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(vp.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(vp.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by vp.paid_at desc nulls last,vp.id desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _reviews(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select id,event_type,site,vendor_code,event_time,confidence,requires_confirmation,status,created_at
        from candidate_events where upper(status) in ('PENDING','PENDING_REVIEW','REVIEW')
    """
    params: list[Any] = []
    if site:
        sql += " and (site is null or upper(site)=upper(%s))"
        params.append(site)
    if vendor:
        sql += " and (vendor_code is null or upper(vendor_code)=upper(%s))"
        params.append(vendor)
    sql += " order by created_at desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


@router.get("/operational-context", dependencies=[Depends(require_gpt_auth)])
def operational_context(
    site: Literal["MAJA", "CEMPLANG"] | None = None,
    vendor: str = "",
    as_of: date | None = Query(default=None, alias="asOf"),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Return durable operating rules and current PostgreSQL facts before GPT performs operational reasoning."""
    vendor_code = vendor.upper().strip() or None
    effective_date = as_of or datetime.now(JAKARTA).date()
    sections = {
        "vendorRules": _vendor_rules(site, vendor_code, effective_date, limit),
        "openPurchaseOrders": _open_pos(site, vendor_code, limit),
        "recentGoodsReceipts": _recent_receipts(site, vendor_code, limit),
        "openPayables": _payables(site, vendor_code, limit),
        "recentPayments": _payments(site, vendor_code, limit),
        "reviewQueue": _reviews(site, vendor_code, limit),
    }
    errors = {name: value.get("error") for name, value in sections.items() if value.get("error")}
    return {
        "runtimeVersion": "llm-knowledge-runtime-v1",
        "generatedAt": datetime.now(JAKARTA).isoformat(),
        "asOf": effective_date.isoformat(),
        "databaseReady": database_ready(),
        "site": site,
        "vendorCode": vendor_code,
        "sourceOfTruth": "PostgreSQL for live operational state; canonical runtime rules for durable operating knowledge; Drive for evidence/archive.",
        "canonicalKnowledge": _rules(),
        "liveContext": {name: value.get("items", []) for name, value in sections.items()},
        "sectionErrors": errors,
        "safeToUseForWrites": bool(database_ready() and not errors.get("openPurchaseOrders")),
    }
