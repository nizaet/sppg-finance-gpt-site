from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from backend.db import connection
from backend.operational_api import require_db
from backend.po_schedule import resolve_purchase_order_schedule

router = APIRouter(tags=["purchase-order-listing"])

_ARCHIVE_STATUSES = {"RECEIVED"}
_HISTORY_STATUSES = {"CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"}


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _archive_reason(row: dict[str, Any], today: date) -> str | None:
    status = str(row.get("status") or "").upper()
    if status in _ARCHIVE_STATUSES:
        return "BARANG_SUDAH_DATANG_SEMUA"
    coverage_dates = [_as_date(value) for value in (row.get("coverage_dates") or [])]
    coverage_dates = [value for value in coverage_dates if value]
    last_distribution = max(coverage_dates) if coverage_dates else _as_date(row.get("distribution_date"))
    if last_distribution and last_distribution <= today - timedelta(days=2):
        return "LEWAT_H_PLUS_2"
    return None


@router.get("/purchase-orders-active")
def list_purchase_orders_active(
    site: str = "",
    vendor: str = "",
    status: str = "",
    search: str = "",
    include_archived: bool = Query(default=False, alias="includeArchived"),
    from_date: date | None = Query(default=None, alias="fromDate"),
    to_date: date | None = Query(default=None, alias="toDate"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """PO listing for the operations UI.

    Default view is deliberately short and operational: active/relevant POs from
    H-1 through H+7. Fully received POs and old POs after H+2 are archived by
    default, but remain searchable with includeArchived=true or a search term.
    """
    require_db()
    jakarta_today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    normalized_search = search.strip()

    if not from_date and not to_date and not normalized_search:
        from_date = jakarta_today - timedelta(days=1)
        to_date = jakarta_today + timedelta(days=7)

    sql = """
        select po.id, po.po_code, po.revision_no, po.site, po.vendor_code, po.status,
               po.sent_at, po.acknowledged_at, po.finalized_at, po.created_at,
               pc.distribution_date,pc.cooking_at,
               coalesce((select array_agg(poc.distribution_date order by poc.distribution_date)
                         from purchase_order_coverage poc where poc.purchase_order_id=po.id),
                        array[pc.distribution_date]) as coverage_dates,
               coalesce((select count(*) from purchase_order_coverage poc where poc.purchase_order_id=po.id),1) as coverage_day_count,
               (select count(*) from purchase_order_items poi where poi.purchase_order_id=po.id) as item_count,
               coalesce((select sum(poi.po_qty * coalesce(poi.po_price,0))
                         from purchase_order_items poi where poi.purchase_order_id=po.id),0) as po_total
        from purchase_orders po
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
    if status:
        sql += " and upper(po.status)=upper(%s)"
        params.append(status)
    else:
        sql += " and upper(coalesce(po.status,'')) <> all(%s)"
        params.append(sorted(_HISTORY_STATUSES))
    if from_date:
        sql += " and coalesce((select max(poc.distribution_date) from purchase_order_coverage poc where poc.purchase_order_id=po.id), pc.distribution_date) >= %s"
        params.append(from_date)
    if to_date:
        sql += " and coalesce((select min(poc.distribution_date) from purchase_order_coverage poc where poc.purchase_order_id=po.id), pc.distribution_date) <= %s"
        params.append(to_date)
    if normalized_search:
        pattern = f"%{normalized_search.lower()}%"
        sql += """
          and (
            lower(coalesce(po.po_code,'')) like %s
            or lower(coalesce(po.vendor_code,'')) like %s
            or exists (
              select 1 from purchase_order_items poi
              where poi.purchase_order_id=po.id
                and lower(coalesce(poi.item_name,'')) like %s
            )
          )
        """
        params.extend([pattern, pattern, pattern])
    sql += " order by pc.distribution_date desc nulls last, po.created_at desc limit %s"
    params.append(limit)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            items: list[dict[str, Any]] = []
            archived_count = 0
            for row in rows:
                item = dict(row)
                item.update(resolve_purchase_order_schedule(cur, item))
                reason = _archive_reason(item, jakarta_today)
                item["archived"] = bool(reason)
                item["archive_reason"] = reason
                if reason and not include_archived and not normalized_search:
                    archived_count += 1
                    continue
                items.append(item)
            return {
                "items": items,
                "count": len(items),
                "hiddenArchivedCount": archived_count,
                "defaultWindow": {
                    "fromDate": from_date,
                    "toDate": to_date,
                    "archiveAfter": "H+2",
                },
            }
