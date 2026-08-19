from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import Query

from backend import po_delivery_alerts_api as _alerts
from backend.db import connection
from backend.item_taxonomy import stock_type
from backend.operational_api import name_similarity
from backend.stock_opname_parser import canonical_unit

_ORIGINAL_PO_DELIVERY_ALERTS = _alerts.po_delivery_alerts
_INSTALLED = False


def _same_unit(left: Any, right: Any) -> bool:
    a = canonical_unit(left) or ""
    b = canonical_unit(right) or ""
    if not a or not b:
        return True
    return a == b


def _same_item(left_name: str, left_unit: Any, right_name: str, right_unit: Any) -> bool:
    if not _same_unit(left_unit, right_unit):
        return False
    left_type = stock_type(left_name)
    right_type = stock_type(right_name)
    if (
        left_type.get("method") != "RAW_FALLBACK"
        and right_type.get("method") != "RAW_FALLBACK"
        and left_type.get("code") == right_type.get("code")
    ):
        return True
    score, _ = name_similarity(left_name, {"item_name": right_name, "item_aliases": []})
    return float(score) >= 0.72


def _resolved_po_ids(po_ids: list[int], target: date) -> set[int]:
    if not po_ids:
        return set()
    keys = [f"po-delivery:{po_id}:{target.isoformat()}" for po_id in po_ids]
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select purchase_order_id
                from po_delivery_alert_resolutions
                where alert_key=any(%s)
                  and upper(action)=any(%s)
                """,
                (keys, ["ARRIVED_MATCH", "ARRIVED_MISMATCH", "SUPPRESS_ALERT"]),
            )
            return {int(row["purchase_order_id"]) for row in cur.fetchall()}


def _arrival_evidence(po_rows: list[dict[str, Any]], target: date) -> set[int]:
    """Return PO item ids that have any positive receiving evidence.

    This warning is specifically "barang belum datang", not a variance checker.
    Once an item has a matched receiving row, a shortage belongs in Receiving
    Variance and must not keep the red not-arrived warning alive.

    Evidence can come from the exact PO item, the same planning item on another
    PO, or a deterministic same-site/vendor/item/unit receipt around H-1/H-0.
    The last rule covers legacy/multi-PO receipts whose header was attached to a
    sibling PO even though the physical delivery already arrived.
    """
    po_ids = [int(row["purchaseOrderId"]) for row in po_rows if row.get("purchaseOrderId")]
    if not po_ids:
        return set()

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select poi.id,poi.purchase_order_id,poi.planning_snapshot_item_id,
                       poi.item_name,poi.unit,po.site,po.vendor_code
                from purchase_order_items poi
                join purchase_orders po on po.id=poi.purchase_order_id
                where poi.purchase_order_id=any(%s)
                """,
                (po_ids,),
            )
            alert_items = [dict(row) for row in cur.fetchall()]
            if not alert_items:
                return set()

            sites = sorted({str(row["site"]).upper() for row in alert_items})
            vendors = sorted({str(row["vendor_code"]).upper() for row in alert_items})
            from_date = target - timedelta(days=1)
            to_date = target

            cur.execute(
                """
                select gr.purchase_order_id as receipt_po_id,gr.received_at,
                       rpo.site,rpo.vendor_code,
                       gri.purchase_order_item_id as linked_po_item_id,
                       lpoi.planning_snapshot_item_id as linked_planning_item_id,
                       coalesce(lpoi.item_name,gri.reported_item_name) as receipt_item_name,
                       gri.reported_item_name,gri.unit,
                       coalesce(gri.accepted_qty,gri.received_qty,0) as accepted_qty
                from goods_receipts gr
                join purchase_orders rpo on rpo.id=gr.purchase_order_id
                join goods_receipt_items gri on gri.goods_receipt_id=gr.id
                left join purchase_order_items lpoi on lpoi.id=gri.purchase_order_item_id
                where upper(rpo.site)=any(%s)
                  and upper(rpo.vendor_code)=any(%s)
                  and coalesce(gri.accepted_qty,gri.received_qty,0)>0
                  and (
                    gr.purchase_order_id=any(%s)
                    or date(gr.received_at) between %s and %s
                  )
                order by gr.received_at desc nulls last,gri.id desc
                """,
                (sites, vendors, po_ids, from_date, to_date),
            )
            receipts = [dict(row) for row in cur.fetchall()]

    arrived: set[int] = set()
    for item in alert_items:
        item_id = int(item["id"])
        planning_id = item.get("planning_snapshot_item_id")
        for receipt in receipts:
            if str(receipt.get("site") or "").upper() != str(item.get("site") or "").upper():
                continue
            if str(receipt.get("vendor_code") or "").upper() != str(item.get("vendor_code") or "").upper():
                continue
            linked_item_id = receipt.get("linked_po_item_id")
            if linked_item_id is not None and int(linked_item_id) == item_id:
                arrived.add(item_id)
                break
            linked_planning_id = receipt.get("linked_planning_item_id")
            if planning_id is not None and linked_planning_id is not None and int(planning_id) == int(linked_planning_id):
                arrived.add(item_id)
                break
            receipt_name = str(receipt.get("receipt_item_name") or receipt.get("reported_item_name") or "").strip()
            if receipt_name and _same_item(str(item.get("item_name") or ""), item.get("unit"), receipt_name, receipt.get("unit")):
                arrived.add(item_id)
                break
    return arrived


def po_delivery_alerts(
    site: str = "",
    alert_date: date | None = Query(default=None, alias="date"),
    minimum_hour: int = Query(default=17, ge=0, le=23, alias="minimumHour"),
) -> dict[str, Any]:
    payload = _ORIGINAL_PO_DELIVERY_ALERTS(site=site, alert_date=alert_date, minimum_hour=minimum_hour)
    rows = payload.get("items") or []
    if not rows:
        return payload

    target = alert_date or _alerts._now_jakarta().date()
    po_ids = [int(row["purchaseOrderId"]) for row in rows if row.get("purchaseOrderId")]

    # Belt-and-suspenders: an explicit operator resolution must always win,
    # even if an older base query fails to recognize its JSON payload shape.
    resolved = _resolved_po_ids(po_ids, target)
    unresolved_rows = [row for row in rows if int(row.get("purchaseOrderId") or 0) not in resolved]
    if not unresolved_rows:
        result = dict(payload)
        result.update({"items": [], "count": 0, "resolutionGuardApplied": bool(resolved)})
        return result

    arrived_item_ids = _arrival_evidence(unresolved_rows, target)
    reconciled: list[dict[str, Any]] = []
    hidden_items = 0

    for original_po in unresolved_rows:
        po = dict(original_po)
        missing_items: list[dict[str, Any]] = []
        for original_item in po.get("items") or []:
            item = dict(original_item)
            item_id = int(item.get("purchaseOrderItemId") or 0)

            # The base query may show a partly received line because accepted_qty
            # is below PO qty. For a "belum datang" alert, any positive accepted
            # qty means the item DID arrive; the shortage belongs in variance.
            direct_received = float(item.get("acceptedQty") or 0) > 0
            if direct_received or item_id in arrived_item_ids:
                hidden_items += 1
                continue
            missing_items.append(item)

        if missing_items:
            po["items"] = missing_items
            po["message"] = (
                f"Barang PO {po.get('poCode')} untuk masak {po.get('cookingDate')} belum memiliki penerimaan "
                "untuk sebagian item. Cek item yang benar-benar belum tercatat datang."
            )
            reconciled.append(po)

    result = dict(payload)
    result["items"] = reconciled
    result["count"] = len(reconciled)
    result["receiptArrivalReconcileApplied"] = True
    result["arrivalEvidenceMode"] = "ANY_POSITIVE_MATCHED_RECEIPT"
    result["resolvedPurchaseOrdersHidden"] = len(resolved)
    result["receivedItemsHidden"] = hidden_items
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _alerts.po_delivery_alerts = po_delivery_alerts
    for route in _alerts.router.routes:
        if getattr(route, "path", "") == "/po-delivery-alerts" and "GET" in (getattr(route, "methods", set()) or set()):
            route.endpoint = po_delivery_alerts
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = po_delivery_alerts
    _INSTALLED = True
