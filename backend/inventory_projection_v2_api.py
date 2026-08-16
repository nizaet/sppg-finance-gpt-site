from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection
from backend.inventory_api import classify_item, load_item_matchers, normalize_location
from backend.inventory_summary_api import inventory_balances
from backend.stock_opname_parser import canonical_unit, normalize_name

router = APIRouter(tags=["inventory-projection-v2"])

COMMITTED_PO_STATUSES = ("FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED")


def _item_key(name: Any, unit: Any, masters: list[dict[str, Any]]) -> tuple[str, str]:
    match = classify_item(str(name or ""), masters)
    return normalize_name(str(match.get("canonicalItemName") or name or "")), canonical_unit(unit)


@router.get("/inventory/balances-v2")
def inventory_balances_v2(
    site: str = Query(min_length=1),
    search: str = "",
    limit: int = Query(default=300, ge=1, le=1000),
    for_date: date | None = Query(default=None, alias="forDate"),
) -> dict[str, Any]:
    """Return warehouse projection with committed PO supply before receiving.

    The legacy balance already uses latest SO as the factual anchor and subtracts
    actual/planned production usage after that SO.  This endpoint adds a
    *provisional* supply for committed PO quantities only while no matching goods
    receipt exists yet.  Therefore, for a planned requirement of 30 and a PO of
    20, the warehouse projection falls by 10 (the amount supplied from existing
    stock), not by the full 30.

    As soon as a real goods receipt exists, its PURCHASE_RECEIPT movement is the
    source of truth and this provisional PO supply is not added.  A later SO
    automatically becomes the new anchor through the legacy balance function,
    so prior projection never overrides the physical count.
    """
    base = inventory_balances(site=site, search=search, limit=limit, for_date=for_date)
    stock_date = base.get("latestStockOpnameDate")
    target_date = base.get("forDate")
    if not stock_date or not target_date or not base.get("items"):
        base["projectionModel"] = "SO + facts - usage + provisional committed PO supply"
        return base

    location = normalize_location(site)
    expected: dict[tuple[str, str], float] = {}

    with connection() as conn:
        with conn.cursor() as cur:
            masters = load_item_matchers(cur, None if location == "KOPERASI" else location)
            cur.execute(
                """
                with coverage_rows as (
                  select
                    po.id as purchase_order_id,
                    poc.distribution_date,
                    poci.item_code,
                    poci.item_name,
                    poci.po_qty,
                    poci.unit
                  from purchase_orders po
                  join purchase_order_coverage poc on poc.purchase_order_id=po.id
                  join purchase_order_coverage_items poci on poci.purchase_order_coverage_id=poc.id
                  where upper(po.site)=%s
                    and upper(coalesce(po.status,'')) = any(%s)
                    and coalesce(po.historical_import,false)=false
                    and poc.distribution_date > %s
                    and poc.distribution_date < %s

                  union all

                  select
                    po.id as purchase_order_id,
                    pc.distribution_date,
                    poi.item_code,
                    poi.item_name,
                    poi.po_qty,
                    poi.unit
                  from purchase_orders po
                  join production_cycles pc on pc.id=po.production_cycle_id
                  join purchase_order_items poi on poi.purchase_order_id=po.id
                  where upper(po.site)=%s
                    and upper(coalesce(po.status,'')) = any(%s)
                    and coalesce(po.historical_import,false)=false
                    and pc.distribution_date > %s
                    and pc.distribution_date < %s
                    and not exists (
                      select 1 from purchase_order_coverage poc
                      join purchase_order_coverage_items poci on poci.purchase_order_coverage_id=poc.id
                      where poc.purchase_order_id=po.id
                    )
                )
                select c.purchase_order_id,c.distribution_date,c.item_code,c.item_name,c.po_qty,c.unit
                from coverage_rows c
                where coalesce(c.po_qty,0) > 0
                  and not exists (
                    select 1
                    from goods_receipts gr
                    join goods_receipt_items gri on gri.goods_receipt_id=gr.id
                    left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
                    where gr.purchase_order_id=c.purchase_order_id
                      and date(coalesce(gr.received_at,gr.created_at)) < %s
                      and coalesce(gri.accepted_qty,gri.received_qty,0) > 0
                      and (
                        (c.item_code is not null and poi.item_code=c.item_code)
                        or lower(trim(coalesce(poi.item_name,gri.reported_item_name,'')))=lower(trim(c.item_name))
                      )
                  )
                order by c.distribution_date,c.purchase_order_id
                """,
                (
                    location, list(COMMITTED_PO_STATUSES), stock_date, target_date,
                    location, list(COMMITTED_PO_STATUSES), stock_date, target_date,
                    target_date,
                ),
            )
            for row in cur.fetchall():
                key = _item_key(row.get("item_name"), row.get("unit"), masters)
                expected[key] = expected.get(key, 0.0) + float(row.get("po_qty") or 0)

            item_keys: dict[tuple[str, str], dict[str, Any]] = {}
            for item in base.get("items") or []:
                key = _item_key(item.get("item_name"), item.get("unit"), masters)
                item_keys[key] = item

    for key, amount in expected.items():
        item = item_keys.get(key)
        if not item:
            continue
        amount = round(amount, 4)
        item["expected_po_supply"] = amount
        adjusted = round(float(item.get("projected_balance") or 0) + amount, 4)
        item["balance"] = adjusted
        item["projected_balance"] = adjusted
        item["available_for_po"] = round(max(adjusted, 0), 4)
        if amount > 0:
            item["stock_basis"] = "SO_PLUS_FACTS_MINUS_USAGE_PLUS_COMMITTED_PO_SUPPLY"
            if item.get("confidence") == "HIGH":
                item["confidence"] = "MEDIUM"

    for item in base.get("items") or []:
        item.setdefault("expected_po_supply", 0.0)
        # This is the net quantity taken from warehouse stock when the current
        # depletion is planning-based. It is informational/auditable; actual SO
        # remains the authoritative physical balance when available.
        if float(item.get("planned_depletion") or 0) > 0:
            item["planned_stock_usage"] = round(
                max(0.0, float(item.get("planned_depletion") or 0) - float(item.get("expected_po_supply") or 0)),
                4,
            )
        else:
            item["planned_stock_usage"] = 0.0

    base["projectionModel"] = "SO + actual movements/receipts - actual/planned usage + provisional committed PO supply"
    base["provisionalPoSupply"] = round(sum(expected.values()), 4)
    return base
