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


def _item_refs(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose compact saved-item references used by the PO planner.

    The active-list query already fetched planning item ids and normalized
    item/unit keys, but the React PO planner historically looked for ``item_refs``.
    Without this bridge an existing saved Tempe PO could be shown in the list yet
    the planning row still offered to create another PO. Keep both identifiers so
    old and new PO records are detected without rewriting history.
    """
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for raw_id in row.get("planning_item_ids") or []:
        if raw_id is None:
            continue
        key = (str(raw_id), "", "")
        if key in seen:
            continue
        seen.add(key)
        refs.append({"planning_snapshot_item_id": raw_id})

    for raw_key in row.get("item_keys") or []:
        text = str(raw_key or "").strip()
        if not text:
            continue
        name, sep, unit = text.rpartition("|")
        if not sep:
            name, unit = text, ""
        name = name.strip()
        unit = unit.strip()
        key = ("", name, unit)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"item_name": name, "unit": unit})

    return refs


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

    The relational distribution/coverage date remains the source of truth. For
    canonical PO codes such as PO-CEMPLANG-20260828-KOPERASI-ITEM-DAGING-SAPI,
    the YYYYMMDD segment is used only as a read-time fallback when an older or
    malformed PO has lost its production-cycle/coverage date relation. This
    keeps a valid FINAL PO visible without rewriting operational history.
    """
    require_db()
    jakarta_today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    normalized_search = search.strip()

    if not from_date and not to_date and not normalized_search:
        from_date = jakarta_today - timedelta(days=1)
        to_date = jakarta_today + timedelta(days=7)

    # Read-only recovery for a PO whose relational date metadata is missing.
    # A valid canonical code always contains the distribution YYYYMMDD directly
    # after the site segment. Relational dates still win whenever they exist.
    code_date_sql = (
        "case when po.po_code ~ '^PO-[^-]+-[0-9]{8}-' "
        "then to_date(substring(po.po_code from '^PO-[^-]+-([0-9]{8})-'),'YYYYMMDD') "
        "else null end"
    )
    effective_distribution_sql = f"coalesce(pc.distribution_date, {code_date_sql})"
    last_distribution_sql = (
        "coalesce((select max(poc.distribution_date) from purchase_order_coverage poc "
        f"where poc.purchase_order_id=po.id), pc.distribution_date, {code_date_sql})"
    )
    first_distribution_sql = (
        "coalesce((select min(poc.distribution_date) from purchase_order_coverage poc "
        f"where poc.purchase_order_id=po.id), pc.distribution_date, {code_date_sql})"
    )

    sql = f"""
        select po.id, po.po_code, po.revision_no, po.site, po.vendor_code, po.status,
               po.sent_at, po.acknowledged_at, po.finalized_at, po.created_at,
               {effective_distribution_sql} as distribution_date, pc.cooking_at,
               coalesce((select array_agg(poc.distribution_date order by poc.distribution_date)
                         from purchase_order_coverage poc where poc.purchase_order_id=po.id),
                        array[{effective_distribution_sql}]) as coverage_dates,
               coalesce((select count(*) from purchase_order_coverage poc where poc.purchase_order_id=po.id),1) as coverage_day_count,
               (select count(*) from purchase_order_items poi where poi.purchase_order_id=po.id) as item_count,
               coalesce((
                 select array_agg(distinct poi.planning_snapshot_item_id)
                 from purchase_order_items poi
                 where poi.purchase_order_id=po.id
                   and poi.planning_snapshot_item_id is not null
               ), array[]::bigint[]) as planning_item_ids,
               coalesce((
                 select array_agg(distinct lower(trim(coalesce(poi.item_name,''))) || '|' || lower(trim(coalesce(poi.unit,''))))
                 from purchase_order_items poi
                 where poi.purchase_order_id=po.id
                   and coalesce(poi.po_qty,0)>0
               ), array[]::text[]) as item_keys,
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
        sql += f" and {last_distribution_sql} >= %s"
        params.append(from_date)
    if to_date:
        sql += f" and {first_distribution_sql} <= %s"
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
    sql += f" order by {effective_distribution_sql} desc nulls last, po.created_at desc limit %s"
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
                item["item_refs"] = _item_refs(item)
                reason = _archive_reason(item, jakarta_today)
                item["archived"] = bool(reason)
                item["archive_reason"] = reason
                # Keep recently RECEIVED POs in the active window so the planner
                # can see that an item was already ordered/received and never
                # offer a duplicate PO. Older H+2 history remains hidden.
                should_hide = bool(reason and reason != "BARANG_SUDAH_DATANG_SEMUA" and not include_archived and not normalized_search)
                if should_hide:
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
