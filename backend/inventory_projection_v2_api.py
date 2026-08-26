from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection
from backend.inventory_api import classify_item, load_item_matchers, normalize_location
from backend.inventory_summary_api import inventory_balances
from backend.item_taxonomy import stock_type
from backend.stock_opname_parser import canonical_unit

router = APIRouter(tags=["inventory-projection-v2"])

COMMITTED_PO_STATUSES = ("FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED")
_CONFIDENCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _type_key(name: Any, unit: Any, masters: list[dict[str, Any]]) -> tuple[str, str, str, str]:
    raw_name = str(name or "").strip()
    match = classify_item(raw_name, masters)
    candidate = str(match.get("canonicalItemName") or raw_name)
    typed = stock_type(candidate)
    if typed["method"] == "RAW_FALLBACK":
        raw_typed = stock_type(raw_name)
        if raw_typed["method"] != "RAW_FALLBACK":
            typed = raw_typed
    return typed["code"], canonical_unit(unit), typed["label"], typed["method"]


def _empty_row(label: str, unit: str, type_code: str, method: str) -> dict[str, Any]:
    return {
        "item_name": label,
        "inventory_item_code": None,
        "unit": unit,
        "area_codes": [],
        "raw_item_names": [],
        "classification_status": "MATCHED" if method == "ITEM_TYPE_RULE" else "UNMAPPED",
        "classification_method": method,
        "so_qty": 0.0,
        "movement_delta": 0.0,
        "actual_usage_depletion": 0.0,
        "planned_depletion": 0.0,
        "expected_po_supply": 0.0,
        "stock_type_code": type_code,
        "stock_type_method": method,
        "last_movement_at": None,
        "confidence": "LOW",
        "stock_as_of": None,
        "stock_age_days": None,
    }


def _merge_base_rows(base_items: list[dict[str, Any]], masters: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in base_items:
        type_code, unit, label, method = _type_key(item.get("item_name"), item.get("unit"), masters)
        key = (type_code, unit)
        row = grouped.setdefault(key, _empty_row(label, unit, type_code, method))
        for field in ("so_qty", "movement_delta", "actual_usage_depletion"):
            row[field] += float(item.get(field) or 0)
        row["stock_as_of"] = item.get("stock_as_of") or row.get("stock_as_of")
        age = item.get("stock_age_days")
        if age is not None:
            row["stock_age_days"] = max(int(age), int(row.get("stock_age_days") or 0))
        if item.get("last_movement_at") and (row.get("last_movement_at") is None or item["last_movement_at"] > row["last_movement_at"]):
            row["last_movement_at"] = item["last_movement_at"]
        for name in [item.get("item_name"), *(item.get("raw_item_names") or [])]:
            if name and name not in row["raw_item_names"]:
                row["raw_item_names"].append(name)
        for area in item.get("area_codes") or []:
            if area and area not in row["area_codes"]:
                row["area_codes"].append(area)
        if row.get("inventory_item_code") is None and item.get("inventory_item_code"):
            row["inventory_item_code"] = item["inventory_item_code"]
        current_conf = str(row.get("confidence") or "LOW").upper()
        incoming_conf = str(item.get("confidence") or "LOW").upper()
        if _CONFIDENCE_RANK.get(incoming_conf, 1) < _CONFIDENCE_RANK.get(current_conf, 1):
            row["confidence"] = incoming_conf
        elif current_conf == "LOW" and incoming_conf in _CONFIDENCE_RANK:
            row["confidence"] = incoming_conf
    return grouped


@router.get("/inventory/balances-v2")
def inventory_balances_v2(
    site: str = Query(min_length=1),
    search: str = "",
    limit: int = Query(default=300, ge=1, le=1000),
    for_date: date | None = Query(default=None, alias="forDate"),
) -> dict[str, Any]:
    """Taxonomy-aware warehouse projection.

    All stock facts are grouped by ingredient type rather than raw SKU wording.
    Latest SO remains the physical anchor. After that anchor we apply actual
    movements/usage, taxonomy-matched planning depletion, and committed PO supply
    that has not yet become a real goods receipt.
    """
    base = inventory_balances(site=site, search="", limit=1000, for_date=for_date)
    stock_date = base.get("latestStockOpnameDate")
    target_date = base.get("forDate")
    location = normalize_location(site)
    if not target_date:
        return base

    with connection() as conn:
        with conn.cursor() as cur:
            masters = load_item_matchers(cur, None if location == "KOPERASI" else location)
            grouped = _merge_base_rows(base.get("items") or [], masters)

            production_usage_dates: set[tuple[str, str, date]] = set()
            actual_usage_dates: set[tuple[str, str, date]] = set()
            if stock_date:
                cur.execute(
                    """
                    select item_name,unit,date(coalesce(occurred_at,created_at)) usage_date
                    from inventory_movements
                    where upper(coalesce(from_location,''))=%s
                      and upper(coalesce(movement_type,''))='PRODUCTION_USAGE'
                      and date(coalesce(occurred_at,created_at)) > %s
                      and date(coalesce(occurred_at,created_at)) < %s
                    """,
                    (location, stock_date, target_date),
                )
                for row in cur.fetchall():
                    type_code, unit, _, _ = _type_key(row.get("item_name"), row.get("unit"), masters)
                    production_usage_dates.add((type_code, unit, row["usage_date"]))

                if location in {"MAJA", "CEMPLANG"}:
                    cur.execute(
                        """
                        select au.item_name,au.unit,pc.distribution_date
                        from actual_usage au
                        join production_cycles pc on pc.id=au.production_cycle_id
                        where upper(pc.site)=%s
                          and pc.distribution_date > %s
                          and pc.distribution_date < %s
                        """,
                        (location, stock_date, target_date),
                    )
                    for row in cur.fetchall():
                        type_code, unit, _, _ = _type_key(row.get("item_name"), row.get("unit"), masters)
                        actual_usage_dates.add((type_code, unit, row["distribution_date"]))

                    cur.execute(
                        """
                        select psi.item_name,psi.planned_qty,psi.unit,ps.distribution_date
                        from (
                          -- Do not restore stock simply because a completed
                          -- daily plan was later superseded by a newer snapshot.
                          select distinct on (site,distribution_date) id,site,distribution_date
                          from planning_snapshots
                          where upper(site)=%s and status <> 'REJECTED'
                            and distribution_date > %s and distribution_date < %s
                          order by site,distribution_date,created_at desc,id desc
                        ) ps
                        join planning_snapshot_items psi on psi.planning_snapshot_id=ps.id
                        where coalesce(psi.planned_qty,0)>0
                        """,
                        (location, stock_date, target_date),
                    )
                    for plan in cur.fetchall():
                        type_code, unit, label, method = _type_key(plan.get("item_name"), plan.get("unit"), masters)
                        usage_key = (type_code, unit, plan["distribution_date"])
                        if usage_key in actual_usage_dates or usage_key in production_usage_dates:
                            continue
                        key = (type_code, unit)
                        row = grouped.setdefault(key, _empty_row(label, unit, type_code, method))
                        row["planned_depletion"] += float(plan.get("planned_qty") or 0)
                        if plan.get("item_name") and plan["item_name"] not in row["raw_item_names"]:
                            row["raw_item_names"].append(plan["item_name"])

            expected: dict[tuple[str, str], float] = {}
            if stock_date:
                cur.execute(
                    """
                    with coverage_rows as (
                      select po.id purchase_order_id,poc.distribution_date,poci.item_name,poci.po_qty,poci.unit
                      from purchase_orders po
                      join purchase_order_coverage poc on poc.purchase_order_id=po.id
                      join purchase_order_coverage_items poci on poci.purchase_order_coverage_id=poc.id
                      where upper(po.site)=%s
                        and upper(coalesce(po.status,''))=any(%s)
                        and coalesce(po.historical_import,false)=false
                        and poc.distribution_date > %s and poc.distribution_date < %s
                      union all
                      select po.id purchase_order_id,pc.distribution_date,poi.item_name,poi.po_qty,poi.unit
                      from purchase_orders po
                      join production_cycles pc on pc.id=po.production_cycle_id
                      join purchase_order_items poi on poi.purchase_order_id=po.id
                      where upper(po.site)=%s
                        and upper(coalesce(po.status,''))=any(%s)
                        and coalesce(po.historical_import,false)=false
                        and pc.distribution_date > %s and pc.distribution_date < %s
                        and not exists (
                          select 1 from purchase_order_coverage poc where poc.purchase_order_id=po.id
                        )
                    )
                    select * from coverage_rows where coalesce(po_qty,0)>0
                    order by distribution_date,purchase_order_id
                    """,
                    (location, list(COMMITTED_PO_STATUSES), stock_date, target_date,
                     location, list(COMMITTED_PO_STATUSES), stock_date, target_date),
                )
                po_rows = cur.fetchall()
                po_ids = sorted({int(row["purchase_order_id"]) for row in po_rows})
                received_types: set[tuple[int, str, str]] = set()
                if po_ids:
                    cur.execute(
                        """
                        select gr.purchase_order_id,
                               coalesce(poi.item_name,gri.reported_item_name) item_name,
                               coalesce(gri.unit,poi.unit) unit
                        from goods_receipts gr
                        join goods_receipt_items gri on gri.goods_receipt_id=gr.id
                        left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
                        where gr.purchase_order_id=any(%s)
                          and date(coalesce(gr.received_at,gr.created_at)) < %s
                          and coalesce(gri.accepted_qty,gri.received_qty,0)>0
                        """,
                        (po_ids, target_date),
                    )
                    for receipt in cur.fetchall():
                        type_code, unit, _, _ = _type_key(receipt.get("item_name"), receipt.get("unit"), masters)
                        received_types.add((int(receipt["purchase_order_id"]), type_code, unit))

                for po_row in po_rows:
                    type_code, unit, label, method = _type_key(po_row.get("item_name"), po_row.get("unit"), masters)
                    if (int(po_row["purchase_order_id"]), type_code, unit) in received_types:
                        continue
                    key = (type_code, unit)
                    expected[key] = expected.get(key, 0.0) + float(po_row.get("po_qty") or 0)
                    row = grouped.setdefault(key, _empty_row(label, unit, type_code, method))
                    if po_row.get("item_name") and po_row["item_name"] not in row["raw_item_names"]:
                        row["raw_item_names"].append(po_row["item_name"])

    items: list[dict[str, Any]] = []
    search_lower = search.strip().lower()
    for key, row in grouped.items():
        expected_supply = round(expected.get(key, 0.0), 4)
        so_qty = round(float(row.get("so_qty") or 0), 4)
        movement_delta = round(float(row.get("movement_delta") or 0), 4)
        actual_usage = round(float(row.get("actual_usage_depletion") or 0), 4)
        planned = round(float(row.get("planned_depletion") or 0), 4)
        actual_balance = round(so_qty + movement_delta - actual_usage, 4)
        projected = round(actual_balance - planned + expected_supply, 4)
        row.update({
            "so_qty": so_qty,
            "movement_delta": movement_delta,
            "actual_usage_depletion": actual_usage,
            "planned_depletion": planned,
            "expected_po_supply": expected_supply,
            "planned_stock_usage": round(max(0.0, planned - expected_supply), 4),
            "actual_balance": actual_balance,
            "projected_balance": projected,
            "balance": projected,
            "available_for_po": round(max(projected, 0), 4),
            "stock_basis": "TYPE_CLASSIFIED_SO_PLUS_FACTS_MINUS_USAGE_PLUS_COMMITTED_PO_SUPPLY",
        })
        if expected_supply > 0 and row.get("confidence") == "HIGH":
            row["confidence"] = "MEDIUM"
        haystack = " ".join([str(row.get("item_name") or ""), *(str(x) for x in row.get("raw_item_names") or [])]).lower()
        if search_lower and search_lower not in haystack:
            continue
        items.append(row)

    items.sort(key=lambda item: str(item.get("item_name") or "").lower())
    base["items"] = items[:limit]
    base["count"] = len(base["items"])
    base["projectionModel"] = "TYPE_CLASSIFIED: latest SO + facts - actual/planned usage + provisional committed PO supply"
    base["classificationModel"] = "ingredient_type_not_brand_or_variety"
    base["provisionalPoSupply"] = round(sum(expected.values()), 4)
    return base
