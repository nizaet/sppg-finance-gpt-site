from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection
from backend.operational_api import require_db

router = APIRouter(tags=["goods-receipt-visibility"])


@router.get("/goods-receipts-visible")
def list_goods_receipts_visible(
    site: str = "",
    vendor: str = "",
    po_id: int | None = Query(default=None, alias="poId"),
    po_code: str = Query(default="", alias="poCode"),
    from_date: date | None = Query(default=None, alias="fromDate"),
    to_date: date | None = Query(default=None, alias="toDate"),
    distribution_date: date | None = Query(default=None, alias="distributionDate"),
    search: str = "",
    limit: int = Query(default=150, ge=1, le=500),
) -> dict[str, Any]:
    """Receipt history for the operations UI, including item-level rows.

    The older /goods-receipts endpoint only returned receipt headers and totals.
    That made GPTS-entered receipts look missing when the operator searched by
    item, PO, receiving date, or distribution date. This endpoint keeps the
    receipt header but embeds every goods_receipt_item so the UI can show exactly
    what was committed to stock.
    """
    require_db()
    normalized_search = search.strip().lower()

    sql = """
        select gr.id, gr.receipt_code, gr.received_at, gr.reporter, gr.source_type,
               gr.source_external_id, gr.match_status, gr.match_confidence,
               po.id as purchase_order_id, po.po_code, po.site, po.vendor_code,
               po.status as po_status,
               pc.distribution_date, pc.cooking_at,
               count(gri.id) as item_count,
               coalesce(sum(gri.received_qty),0) as received_qty_total,
               coalesce(sum(gri.accepted_qty),0) as accepted_qty_total,
               coalesce(sum(gri.rejected_qty),0) as rejected_qty_total
        from goods_receipts gr
        join purchase_orders po on po.id=gr.purchase_order_id
        left join production_cycles pc on pc.id=po.production_cycle_id
        left join goods_receipt_items gri on gri.goods_receipt_id=gr.id
        where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    if po_id is not None:
        sql += " and po.id=%s"
        params.append(po_id)
    if po_code:
        sql += " and upper(po.po_code)=upper(%s)"
        params.append(po_code)
    if from_date:
        sql += " and date(gr.received_at) >= %s"
        params.append(from_date)
    if to_date:
        sql += " and date(gr.received_at) <= %s"
        params.append(to_date)
    if distribution_date:
        sql += " and pc.distribution_date = %s"
        params.append(distribution_date)
    if normalized_search:
        pattern = f"%{normalized_search}%"
        sql += """
          and (
            lower(coalesce(po.po_code,'')) like %s
            or lower(coalesce(po.vendor_code,'')) like %s
            or lower(coalesce(gr.reporter,'')) like %s
            or exists (
              select 1 from goods_receipt_items gri2
              left join purchase_order_items poi2 on poi2.id=gri2.purchase_order_item_id
              where gri2.goods_receipt_id=gr.id
                and (
                  lower(coalesce(gri2.reported_item_name,'')) like %s
                  or lower(coalesce(poi2.item_name,'')) like %s
                )
            )
          )
        """
        params.extend([pattern, pattern, pattern, pattern, pattern])

    sql += """
        group by gr.id, po.id, pc.id
        order by gr.received_at desc nulls last, gr.id desc
        limit %s
    """
    params.append(limit)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]
            if not rows:
                return {"items": [], "count": 0}

            receipt_ids = [row["id"] for row in rows]
            cur.execute(
                """
                select gri.id as receipt_item_id, gri.goods_receipt_id,
                       gri.purchase_order_item_id, gri.reported_item_name,
                       poi.item_name as po_item_name, poi.item_code as po_item_code,
                       gri.po_qty_snapshot, gri.received_qty, gri.accepted_qty,
                       gri.rejected_qty, gri.variance_qty, gri.unit,
                       gri.quality_status, gri.match_confidence, gri.match_method,
                       gri.notes
                from goods_receipt_items gri
                left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
                where gri.goods_receipt_id = any(%s)
                order by gri.goods_receipt_id desc, gri.id
                """,
                (receipt_ids,),
            )
            grouped: dict[int, list[dict[str, Any]]] = {int(row["id"]): [] for row in rows}
            for item in cur.fetchall():
                grouped.setdefault(int(item["goods_receipt_id"]), []).append(dict(item))

    for row in rows:
        row["items"] = grouped.get(int(row["id"]), [])
        row["item_names"] = [
            item.get("po_item_name") or item.get("reported_item_name")
            for item in row["items"]
            if item.get("po_item_name") or item.get("reported_item_name")
        ]
    return {"items": rows, "count": len(rows)}
