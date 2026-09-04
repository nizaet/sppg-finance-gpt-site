from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.db import connection, database_ready

router = APIRouter(tags=["operational-search"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


@router.get("/purchase-orders/search")
def search_purchase_orders(
    site: str = "",
    vendor: str = "",
    po_code: str = Query(default="", alias="poCode"),
    distribution_date: date | None = Query(default=None, alias="distributionDate"),
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    status: str = "",
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Read-only PO search for GPT reconciliation."""
    require_db()
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "dateFrom must be on or before dateTo")
    sql = """
        select po.id as purchase_order_id, po.po_code, po.revision_no, po.site,
               po.vendor_code, po.status, po.sent_at, po.acknowledged_at,
               po.finalized_at, po.created_at, pc.distribution_date,
               count(poi.id) as item_count
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        left join purchase_order_items poi on poi.purchase_order_id=po.id
        where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    if po_code:
        sql += " and upper(po.po_code)=upper(%s)"
        params.append(po_code)
    if distribution_date is not None:
        sql += " and pc.distribution_date=%s"
        params.append(distribution_date)
    if date_from is not None:
        sql += " and pc.distribution_date>=%s"
        params.append(date_from)
    if date_to is not None:
        sql += " and pc.distribution_date<=%s"
        params.append(date_to)
    if status:
        sql += " and upper(po.status)=upper(%s)"
        params.append(status)
    sql += " group by po.id,pc.id order by pc.distribution_date desc nulls last,po.created_at desc limit %s"
    params.append(limit)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            for row in rows:
                cur.execute(
                    """select id as purchase_order_item_id,item_code,item_name,planned_qty,po_qty,unit,
                              planning_price,po_price,item_aliases,notes
                       from purchase_order_items where purchase_order_id=%s order by id""",
                    (row["purchase_order_id"],),
                )
                row["items"] = cur.fetchall()
    return {"items": rows, "count": len(rows)}


@router.get("/goods-receipts/search")
def search_goods_receipts(
    site: str = "",
    vendor: str = "",
    purchase_order_id: int | None = Query(default=None, alias="purchaseOrderId"),
    distribution_date: date | None = Query(default=None, alias="distributionDate"),
    received_date: date | None = Query(default=None, alias="receivedDate"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Read-only goods receipt search with receipt items."""
    require_db()
    sql = """
        select gr.id as goods_receipt_id, gr.purchase_order_id, gr.receipt_code,
               gr.received_at, gr.source_type, gr.source_external_id, gr.reporter,
               gr.match_status, gr.match_confidence, po.po_code, po.site,
               po.vendor_code, po.status as purchase_order_status, pc.distribution_date
        from goods_receipts gr
        join purchase_orders po on po.id=gr.purchase_order_id
        left join production_cycles pc on pc.id=po.production_cycle_id
        where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    if purchase_order_id is not None:
        sql += " and po.id=%s"
        params.append(purchase_order_id)
    if distribution_date is not None:
        sql += " and pc.distribution_date=%s"
        params.append(distribution_date)
    if received_date is not None:
        sql += " and date(gr.received_at)=%s"
        params.append(received_date)
    sql += " order by gr.received_at desc nulls last,gr.id desc limit %s"
    params.append(limit)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            for row in rows:
                cur.execute(
                    """select gri.id as goods_receipt_item_id,gri.purchase_order_item_id,
                              coalesce(poi.item_name,gri.reported_item_name) as item_name,
                              gri.reported_item_name,gri.po_qty_snapshot,gri.received_qty,
                              gri.rejected_qty,gri.accepted_qty,gri.variance_qty,gri.unit,
                              gri.quality_status,gri.match_confidence,gri.match_method,
                              poi.planned_qty,poi.po_qty,poi.planning_price,poi.po_price
                       from goods_receipt_items gri
                       left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
                       where gri.goods_receipt_id=%s order by gri.id""",
                    (row["goods_receipt_id"],),
                )
                row["items"] = cur.fetchall()
    return {"items": rows, "count": len(rows)}
