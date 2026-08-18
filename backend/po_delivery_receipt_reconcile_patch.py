from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import Query

from backend import po_delivery_alerts_api as _alerts
from backend.db import connection
from backend.item_taxonomy import stock_type
from backend.operational_api import name_similarity
from backend.stock_opname_parser import canonical_unit

_ORIGINAL_PO_DELIVERY_ALERTS = _alerts.po_delivery_alerts
_EPSILON = 0.0001
_INSTALLED = False


def _same_unit(left: Any, right: Any) -> bool:
    a = canonical_unit(left) or ""
    b = canonical_unit(right) or ""
    if not a or not b:
        return True
    return a == b


def _pick_po_item(receipt: dict[str, Any], po_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Resolve an unlinked receipt item only when the match is unambiguous.

    The receipt is already attached to one purchase_order_id at header level, so
    matching never crosses PO boundaries. Ingredient taxonomy + unit is preferred;
    fuzzy name matching is only a guarded fallback.
    """
    reported_name = str(receipt.get("reported_item_name") or "").strip()
    if not reported_name:
        return None

    reported_type = stock_type(reported_name)
    typed = [
        item for item in po_items
        if stock_type(item.get("item_name"))["code"] == reported_type["code"]
        and _same_unit(receipt.get("unit"), item.get("unit"))
    ]
    if reported_type.get("method") != "RAW_FALLBACK" and len(typed) == 1:
        return typed[0]

    candidates = typed if typed else [
        item for item in po_items if _same_unit(receipt.get("unit"), item.get("unit"))
    ]
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in candidates:
        score, _ = name_similarity(reported_name, item)
        ranked.append((float(score), item))
    ranked.sort(key=lambda row: row[0], reverse=True)
    if not ranked or ranked[0][0] < 0.72:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.10:
        return None
    return ranked[0][1]


def _fallback_received_by_item(po_ids: list[int]) -> dict[int, float]:
    if not po_ids:
        return {}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id,purchase_order_id,item_name,unit,po_qty
                from purchase_order_items
                where purchase_order_id=any(%s)
                order by purchase_order_id,id
                """,
                (po_ids,),
            )
            po_items: dict[int, list[dict[str, Any]]] = {}
            for row in cur.fetchall():
                po_items.setdefault(int(row["purchase_order_id"]), []).append(dict(row))

            cur.execute(
                """
                select gr.purchase_order_id,gri.id receipt_item_id,
                       gri.reported_item_name,gri.unit,
                       coalesce(gri.accepted_qty,gri.received_qty,0) accepted_qty
                from goods_receipts gr
                join goods_receipt_items gri on gri.goods_receipt_id=gr.id
                where gr.purchase_order_id=any(%s)
                  and gri.purchase_order_item_id is null
                  and coalesce(gri.accepted_qty,gri.received_qty,0)>0
                order by gr.purchase_order_id,gri.id
                """,
                (po_ids,),
            )
            fallback: dict[int, float] = {}
            for receipt in cur.fetchall():
                po_id = int(receipt["purchase_order_id"])
                matched = _pick_po_item(dict(receipt), po_items.get(po_id, []))
                if not matched:
                    continue
                item_id = int(matched["id"])
                fallback[item_id] = fallback.get(item_id, 0.0) + float(receipt.get("accepted_qty") or 0)
            return fallback


def po_delivery_alerts(
    site: str = "",
    alert_date: date | None = Query(default=None, alias="date"),
    minimum_hour: int = Query(default=17, ge=0, le=23, alias="minimumHour"),
) -> dict[str, Any]:
    payload = _ORIGINAL_PO_DELIVERY_ALERTS(site=site, alert_date=alert_date, minimum_hour=minimum_hour)
    rows = payload.get("items") or []
    if not rows:
        return payload

    po_ids = [int(row["purchaseOrderId"]) for row in rows if row.get("purchaseOrderId")]
    fallback = _fallback_received_by_item(po_ids)
    if not fallback:
        return payload

    reconciled: list[dict[str, Any]] = []
    matched_receipt_qty = 0.0
    for original_po in rows:
        po = dict(original_po)
        remaining_items: list[dict[str, Any]] = []
        for original_item in po.get("items") or []:
            item = dict(original_item)
            item_id = int(item.get("purchaseOrderItemId") or 0)
            extra = max(0.0, float(fallback.get(item_id, 0.0)))
            if extra <= _EPSILON:
                remaining_items.append(item)
                continue

            po_qty = float(item.get("poQty") or 0)
            direct_accepted = float(item.get("acceptedQty") or 0)
            accepted = min(po_qty, direct_accepted + extra)
            remaining = max(0.0, round(po_qty - accepted, 4))
            matched_receipt_qty += min(extra, max(0.0, po_qty - direct_accepted))
            item["acceptedQty"] = round(accepted, 4)
            item["receiptFallbackAcceptedQty"] = round(extra, 4)
            item["remainingReceiveQty"] = remaining
            item["receiptLinkFallbackApplied"] = True
            if remaining > _EPSILON:
                unit = item.get("unit") or ""
                item["message"] = f"{item.get('itemName') or 'Item'} belum datang/cukup: kurang {remaining:g} {unit}".strip()
                remaining_items.append(item)

        if remaining_items:
            po["items"] = remaining_items
            reconciled.append(po)

    result = dict(payload)
    result["items"] = reconciled
    result["count"] = len(reconciled)
    result["receiptLinkFallbackApplied"] = True
    result["receiptFallbackAcceptedQty"] = round(matched_receipt_qty, 4)
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _alerts.po_delivery_alerts = po_delivery_alerts
    # APIRoute keeps the callable in both endpoint and dependant.call. Patch both
    # before backend.__init__ includes this router in the public /v1 router.
    for route in _alerts.router.routes:
        if getattr(route, "path", "") == "/po-delivery-alerts" and "GET" in (getattr(route, "methods", set()) or set()):
            route.endpoint = po_delivery_alerts
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = po_delivery_alerts
    _INSTALLED = True
