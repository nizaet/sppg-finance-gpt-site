from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from backend.db import connection, database_ready
from backend.inventory_api import classify_item, load_item_matchers, normalize_location
from backend.stock_opname_parser import canonical_unit, normalize_name

router = APIRouter(tags=["inventory-summary"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _key(name: str, unit: str | None, masters: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    match = classify_item(name, masters)
    canonical_name = match["canonicalItemName"]
    return normalize_name(canonical_name), canonical_unit(unit), match


def _new_row(name: str, unit: str, match: dict[str, Any]) -> dict[str, Any]:
    known_names = list(dict.fromkeys([name, match["canonicalItemName"], *(match.get("knownAliases") or [])]))
    return {
        "item_name": match["canonicalItemName"],
        "inventory_item_code": match["inventoryItemCode"],
        "unit": unit,
        "area_codes": [],
        "raw_item_names": known_names,
        "classification_status": match["classificationStatus"],
        "classification_method": match["classificationMethod"],
        "so_qty": 0.0,
        "movement_delta": 0.0,
        "actual_usage_depletion": 0.0,
        "planned_depletion": 0.0,
        "last_movement_at": None,
    }


def _confidence(has_so: bool, stock_age_days: int | None, planned_depletion: float, classification_status: str) -> str:
    if not has_so or classification_status == "AMBIGUOUS" or (stock_age_days is not None and stock_age_days > 3):
        return "LOW"
    if planned_depletion > 0 or classification_status == "UNMAPPED" or (stock_age_days is not None and stock_age_days > 1):
        return "MEDIUM"
    return "HIGH"


@router.get("/inventory/balances")
def inventory_balances(
    site: str = Query(min_length=1),
    search: str = "",
    limit: int = Query(default=300, ge=1, le=1000),
    for_date: date | None = Query(default=None, alias="forDate"),
) -> dict[str, Any]:
    """Stock before forDate from the latest SO, later facts, and prior plans.

    Planning for forDate itself is excluded so projected stock can safely be
    subtracted from that date's PO requirement.
    """

    require_db()
    location = normalize_location(site)
    jakarta = ZoneInfo("Asia/Jakarta")
    target_date = for_date or (datetime.now(jakarta).date() + timedelta(days=1))
    timezone_name = str(jakarta)

    with connection() as conn:
        with conn.cursor() as cur:
            masters = load_item_matchers(cur, None if location == "KOPERASI" else location)
            cur.execute(
                """
                select id,stock_date,warning_count,source_external_id,created_at
                from stock_opnames
                where location_code=%s and stock_date <= %s
                  and coalesce(status,'ACTIVE')='ACTIVE'
                order by stock_date desc,created_at desc limit 1
                """,
                (location, target_date),
            )
            latest_so = cur.fetchone()
            same_date_opnames: list[dict[str, Any]] = []
            if latest_so:
                cur.execute(
                    """
                    select id,source_external_id,created_at
                    from stock_opnames
                    where location_code=%s and stock_date=%s
                      and coalesce(status,'ACTIVE')='ACTIVE'
                    order by created_at desc,id desc
                    """,
                    (location, latest_so["stock_date"]),
                )
                same_date_opnames = cur.fetchall()

            rows: dict[tuple[str, str], dict[str, Any]] = {}
            if latest_so:
                cur.execute(
                    """
                    select area_code,raw_item_name,canonical_item_name,inventory_item_code,qty,unit
                    from stock_opname_items where stock_opname_id=%s order by id
                    """,
                    (latest_so["id"],),
                )
                for item in cur.fetchall():
                    # A human-reviewed canonical name is the persisted truth for
                    # the baseline. Reclassifying only the raw WhatsApp label can
                    # turn “Mama Lemon” back into fruit or “mi telur” into egg.
                    baseline_name = item["canonical_item_name"] or item["raw_item_name"]
                    normalized, unit, match = _key(baseline_name, item["unit"], masters)
                    key = (normalized, unit)
                    row = rows.setdefault(key, _new_row(baseline_name, unit, match))
                    row["so_qty"] += float(item["qty"] or 0)
                    if item["area_code"] and item["area_code"] not in row["area_codes"]:
                        row["area_codes"].append(item["area_code"])
                    if item["raw_item_name"] not in row["raw_item_names"]:
                        row["raw_item_names"].append(item["raw_item_name"])

            stock_date = latest_so["stock_date"] if latest_so else None
            movement_sql = """
                select item_name,qty,unit,from_location,to_location,movement_type,
                       coalesce(occurred_at,created_at) as occurred_at
                from inventory_movements
                where (upper(coalesce(to_location,''))=%s or upper(coalesce(from_location,''))=%s)
                  and date(coalesce(occurred_at,created_at)) < %s
            """
            movement_params: list[Any] = [location, location, target_date]
            if stock_date:
                movement_sql += " and date(coalesce(occurred_at,created_at)) > %s"
                movement_params.append(stock_date)
            cur.execute(movement_sql, movement_params)
            actual_movement_dates: set[tuple[str, str, date]] = set()
            for movement in cur.fetchall():
                normalized, unit, match = _key(movement["item_name"], movement["unit"], masters)
                key = (normalized, unit)
                row = rows.setdefault(key, _new_row(movement["item_name"], unit, match))
                qty = float(movement["qty"] or 0)
                if str(movement["to_location"] or "").upper() == location:
                    row["movement_delta"] += qty
                if str(movement["from_location"] or "").upper() == location:
                    row["movement_delta"] -= qty
                occurred = movement["occurred_at"]
                if row["last_movement_at"] is None or occurred > row["last_movement_at"]:
                    row["last_movement_at"] = occurred
                if str(movement["movement_type"] or "").upper() == "PRODUCTION_USAGE":
                    actual_movement_dates.add((normalized, unit, occurred.date()))

            if location in {"MAJA", "CEMPLANG"} and stock_date:
                cur.execute(
                    """
                    select au.item_name,au.actual_used_qty,au.unit,pc.distribution_date
                    from actual_usage au join production_cycles pc on pc.id=au.production_cycle_id
                    where upper(pc.site)=%s and pc.distribution_date > %s and pc.distribution_date < %s
                    """,
                    (location, stock_date, target_date),
                )
                actual_usage_dates: set[tuple[str, str, date]] = set()
                for usage in cur.fetchall():
                    normalized, unit, match = _key(usage["item_name"], usage["unit"], masters)
                    key = (normalized, unit)
                    usage_date = usage["distribution_date"]
                    actual_usage_dates.add((normalized, unit, usage_date))
                    if (normalized, unit, usage_date) in actual_movement_dates:
                        continue
                    row = rows.setdefault(key, _new_row(usage["item_name"], unit, match))
                    row["actual_usage_depletion"] += float(usage["actual_used_qty"] or 0)

                cur.execute(
                    """
                    select psi.item_name,psi.planned_qty,psi.unit,ps.distribution_date
                    from (
                      select distinct on (site,distribution_date) id,site,distribution_date
                      from planning_snapshots
                      where upper(site)=%s and status='ACTIVE'
                        and distribution_date > %s and distribution_date < %s
                      order by site,distribution_date,created_at desc,id desc
                    ) ps
                    join planning_snapshot_items psi on psi.planning_snapshot_id=ps.id
                    """,
                    (location, stock_date, target_date),
                )
                for plan in cur.fetchall():
                    normalized, unit, _ = _key(plan["item_name"], plan["unit"], masters)
                    usage_key = (normalized, unit, plan["distribution_date"])
                    if usage_key in actual_usage_dates or usage_key in actual_movement_dates:
                        continue
                    key = (normalized, unit)
                    if key not in rows:
                        continue
                    rows[key]["planned_depletion"] += float(plan["planned_qty"] or 0)

    items: list[dict[str, Any]] = []
    for row in rows.values():
        actual_balance = row["so_qty"] + row["movement_delta"] - row["actual_usage_depletion"]
        projected_balance = actual_balance - row["planned_depletion"]
        stock_age = max(0, (target_date - stock_date).days - 1) if stock_date else None
        confidence = _confidence(bool(latest_so), stock_age, row["planned_depletion"], row["classification_status"])
        basis = "LEDGER_ONLY"
        if latest_so:
            basis = "SO_PLUS_ACTUAL_FACTS"
            if row["planned_depletion"] > 0:
                basis = "SO_PLUS_ACTUAL_FACTS_MINUS_PLANNED_USAGE"
        item = {
            **row,
            "balance": round(projected_balance, 4),
            "actual_balance": round(actual_balance, 4),
            "projected_balance": round(projected_balance, 4),
            "available_for_po": round(max(projected_balance, 0), 4),
            "so_qty": round(row["so_qty"], 4),
            "movement_delta": round(row["movement_delta"], 4),
            "actual_usage_depletion": round(row["actual_usage_depletion"], 4),
            "planned_depletion": round(row["planned_depletion"], 4),
            "stock_as_of": stock_date,
            "stock_basis": basis,
            "confidence": confidence,
            "stock_age_days": stock_age,
        }
        search_lower = search.strip().lower()
        if search_lower and search_lower not in item["item_name"].lower() and all(search_lower not in x.lower() for x in item["raw_item_names"]):
            continue
        items.append(item)

    items.sort(key=lambda item: item["item_name"].lower())
    items = items[:limit]
    return {
        "site": location,
        "location": location,
        "forDate": target_date,
        "projectionThrough": target_date - timedelta(days=1),
        "timezone": timezone_name,
        "latestStockOpnameId": latest_so["id"] if latest_so else None,
        "latestStockOpnameDate": stock_date,
        "sameDateStockOpnameIds": [row["id"] for row in same_date_opnames],
        "sameDateStockOpnameCount": len(same_date_opnames),
        "baselineNeedsConsolidation": bool(
            latest_so
            and len(same_date_opnames) > 1
            and not str(latest_so.get("source_external_id") or "").startswith("consolidated:")
        ),
        "items": items,
        "count": len(items),
    }
