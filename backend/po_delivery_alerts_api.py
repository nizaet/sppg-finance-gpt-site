from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from backend.db import connection
from backend.operational_api import require_db

router = APIRouter(tags=["po-delivery-alerts"])

_OPEN_DELIVERY_STATUSES = ("FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED")


def _now_jakarta() -> datetime:
    return datetime.now(ZoneInfo("Asia/Jakarta"))


@router.get("/po-delivery-alerts")
def po_delivery_alerts(
    site: str = "",
    alert_date: date | None = Query(default=None, alias="date"),
    minimum_hour: int = Query(default=17, ge=0, le=23, alias="minimumHour"),
) -> dict[str, Any]:
    """Warn after 17:00 when ordered ingredients for today's cooking have not arrived.

    This is read-only. It compares PO qty against cumulative accepted receipt qty
    for POs whose cooking date is the target date. Fully received POs are ignored.
    """
    require_db()
    now = _now_jakarta()
    target = alert_date or now.date()
    active = now.time() >= time(minimum_hour, 0) if target == now.date() else True

    sql = """
      with po_base as (
        select po.id,po.po_code,po.site,po.vendor_code,po.status,po.sent_at,po.created_at,
               pc.distribution_date,
               coalesce(
                 (select min(poc.cooking_date) from purchase_order_coverage poc where poc.purchase_order_id=po.id),
                 date(pc.cooking_at),
                 pc.distribution_date - interval '1 day'
               )::date as cooking_date
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where upper(coalesce(po.status,''))=any(%s)
      ), item_totals as (
        select pb.id purchase_order_id,pb.po_code,pb.site,pb.vendor_code,pb.status,pb.sent_at,pb.created_at,
               pb.distribution_date,pb.cooking_date,
               poi.id purchase_order_item_id,poi.item_name,poi.po_qty,poi.unit,
               coalesce(sum(gri.accepted_qty),0) as accepted_qty
        from po_base pb
        join purchase_order_items poi on poi.purchase_order_id=pb.id
        left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
        where pb.cooking_date=%s
        group by pb.id,pb.po_code,pb.site,pb.vendor_code,pb.status,pb.sent_at,pb.created_at,
                 pb.distribution_date,pb.cooking_date,poi.id,poi.item_name,poi.po_qty,poi.unit
      )
      select * from item_totals
      where coalesce(po_qty,0) > coalesce(accepted_qty,0)
    """
    params: list[Any] = [list(_OPEN_DELIVERY_STATUSES), target]
    if site:
        sql += " and upper(site)=upper(%s)"
        params.append(site)
    sql += " order by cooking_date,vendor_code,po_code,item_name"

    grouped: dict[int, dict[str, Any]] = {}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            for row in cur.fetchall():
                po_id = int(row["purchase_order_id"])
                item = grouped.setdefault(po_id, {
                    "purchaseOrderId": po_id,
                    "poCode": row["po_code"],
                    "site": row["site"],
                    "vendorCode": row["vendor_code"],
                    "status": row["status"],
                    "sentAt": row["sent_at"],
                    "createdAt": row["created_at"],
                    "distributionDate": row["distribution_date"],
                    "cookingDate": row["cooking_date"],
                    "items": [],
                })
                remaining = round(float(row.get("po_qty") or 0) - float(row.get("accepted_qty") or 0), 4)
                item["items"].append({
                    "itemName": row["item_name"],
                    "poQty": float(row.get("po_qty") or 0),
                    "acceptedQty": float(row.get("accepted_qty") or 0),
                    "remainingReceiveQty": remaining,
                    "unit": row.get("unit"),
                    "message": f"{row['item_name']} belum datang/cukup: kurang {remaining:g} {row.get('unit') or ''}".strip(),
                })

    items = list(grouped.values()) if active else []
    for row in items:
        row["warningLevel"] = "CRITICAL_AFTER_17" if active else "PENDING_TIME_WINDOW"
        row["message"] = (
            f"Barang PO {row['poCode']} untuk masak {row['cookingDate']} belum datang lengkap. "
            "Risiko bahan tidak cukup untuk masak hari ini."
        )
    return {
        "site": site.upper() if site else "",
        "date": target,
        "timezone": "Asia/Jakarta",
        "active": active,
        "minimumHour": minimum_hour,
        "count": len(items),
        "items": items,
    }
