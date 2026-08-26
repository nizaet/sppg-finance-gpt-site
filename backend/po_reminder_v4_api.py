from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection, database_ready
from backend.inventory_projection_v2_api import inventory_balances_v2
from backend.item_taxonomy import item_family, stock_type, vendor_for_item
from backend.po_reminder_v2_api import _norm, _rule_for_item
from backend.stock_opname_parser import canonical_unit

router = APIRouter(tags=["po-reminder-v4"])

DONE_STATUSES = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
INACTIVE_STATUSES = {"CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"}
COVERAGE_STATUSES = DONE_STATUSES | {"DRAFT", "FINALIZED"}
OVERDUE_LOOKBACK_DAYS = 7
MAX_LEAD_DAYS = 30
PROJECTION_WORKERS = 4
EPSILON = 0.0001


def _stock_key(name: Any, unit: Any) -> tuple[str, str]:
    typed = stock_type(name)
    return typed["code"], canonical_unit(unit) or ""


def _latest_po(pos: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pos:
        return None
    return max(
        pos,
        key=lambda po: (str(po.get("created_at") or ""), int(po.get("revision_no") or 0)),
    )


def _open_status(po_date: date, target: date) -> str:
    if po_date < target:
        return "OVERDUE"
    if po_date == target:
        return "DUE_TODAY"
    return "UPCOMING"


def _projection_lookup(site: str, distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    """Projected stock immediately before the requested distribution date.

    A legitimate available_for_po value of zero must remain zero. Do not use
    boolean `or` here because that would incorrectly fall back to physical balance
    after projected depletion has reduced available stock to zero.
    """
    try:
        payload = inventory_balances_v2(
            site=site,
            search="",
            limit=1000,
            for_date=distribution_date,
        )
    except Exception:
        return {}, "PROJECTION_UNAVAILABLE"

    lookup: dict[tuple[str, str], float] = {}
    for item in payload.get("items") or []:
        key = _stock_key(item.get("item_name"), item.get("unit"))
        raw_available = item.get("available_for_po")
        if raw_available is None:
            raw_available = item.get("balance")
        available = max(0.0, float(raw_available or 0))
        lookup[key] = max(lookup.get(key, 0.0), available)
    return lookup, str(payload.get("projectionModel") or "INVENTORY_PROJECTION_V2")


def _strict_cemplang_tempe_rule(
    rules: list[dict[str, Any]],
    cook: date,
) -> dict[str, Any] | None:
    """Return only a dedicated Cemplang Tempe rule.

    Generic Koperasi rules and combined TAHU/TEMPE rules are deliberately rejected.
    Until a dedicated Tempe lead time is configured, the reminder reports
    LEAD_TIME_MISSING rather than silently borrowing Tahu/dry-goods lead time.
    """
    candidates: list[dict[str, Any]] = []
    for rule in rules:
        if str(rule.get("vendor_code") or "").upper() != "KOPERASI":
            continue
        site_code = str(rule.get("site_code") or "").upper().strip()
        if site_code not in {"", "CEMPLANG"}:
            continue
        if rule.get("effective_from") and rule["effective_from"] > cook:
            continue
        if rule.get("effective_to") and rule["effective_to"] < cook:
            continue
        category = _norm(rule.get("category_code"))
        # Keep Tempe separate from Tahu. A joint TAHU_TEMPE rule is not accepted.
        if "TEMPE" not in category or "TAHU" in category:
            continue
        candidates.append(rule)

    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            str(r.get("site_code") or "").upper() == "CEMPLANG",
            _norm(r.get("category_code")) == "TEMPE",
            r.get("effective_from") or date.min,
            int(r.get("id") or 0),
        ),
        reverse=True,
    )
    return candidates[0]


def _resolve_procurement_rule(
    rules: list[dict[str, Any]],
    vendor_names: dict[str, str],
    row: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, str]:
    """Resolve vendor + lead-time rule with operator-confirmed Tempe exceptions."""
    site = str(row.get("site") or "").upper().strip()
    family = item_family(row.get("item_name"), row.get("category_code"))
    cook = row["cooking_date"]

    if family == "TEMPE" and site == "MAJA":
        vendor = "KOPERASI"
        # Tempe has its own effective-dated rule.  It must never inherit Tahu,
        # dry-goods, or a hidden hard-coded lead time.
        rule = _rule_for_item(rules, vendor, site, "TEMPE", row.get("item_name"), cook)
        if rule:
            rule = dict(rule)
            rule["vendor_name"] = rule.get("vendor_name") or vendor_names.get(vendor, "Koperasi / Mungki")
        return vendor, rule, "TEMPE"

    if family == "TEMPE" and site == "CEMPLANG":
        vendor = "KOPERASI"
        rule = _strict_cemplang_tempe_rule(rules, cook)
        if rule:
            rule = dict(rule)
            rule["vendor_name"] = rule.get("vendor_name") or vendor_names.get(vendor, "Koperasi / Mungki")
        return vendor, rule, "TEMPE"

    vendor = vendor_for_item(
        row.get("item_name"),
        row.get("category_code"),
        site,
        row.get("preferred_vendor_code"),
    )
    if not vendor:
        return None, None, family

    rule = _rule_for_item(
        rules,
        vendor,
        site,
        row.get("category_code"),
        row.get("item_name"),
        cook,
    )
    bucket = "TOFU" if vendor == "KOPERASI" and family == "TOFU" else "DEFAULT"
    return vendor, rule, bucket


def _coverage_stage(
    relevant_pos: list[dict[str, Any]],
    exact_qty: dict[tuple[int, date, str, str], float],
    distribution_date: date,
    type_code: str,
    unit: str,
    recommended: float,
) -> dict[str, Any]:
    """Classify exact PO coverage for one requirement.

    Coverage is *only* exact distribution date + ingredient type + canonical unit.
    Same-vendor, same-created-date, same-send-date, or latest-vendor PO fallbacks are
    intentionally forbidden.
    """
    rows: list[tuple[dict[str, Any], float]] = []
    for po in relevant_pos:
        status = str(po.get("status") or "").upper()
        if status not in COVERAGE_STATUSES:
            continue
        amount = float(exact_qty.get((int(po["id"]), distribution_date, type_code, unit), 0.0))
        if amount > EPSILON:
            rows.append((po, amount))

    done_rows = [(po, amount) for po, amount in rows if str(po.get("status") or "").upper() in DONE_STATUSES]
    finalized_rows = [(po, amount) for po, amount in rows if str(po.get("status") or "").upper() == "FINALIZED"]
    draft_rows = [(po, amount) for po, amount in rows if str(po.get("status") or "").upper() == "DRAFT"]

    done_qty = sum(amount for _, amount in done_rows)
    finalized_qty = sum(amount for _, amount in finalized_rows)
    draft_qty = sum(amount for _, amount in draft_rows)
    total_qty = done_qty + finalized_qty + draft_qty

    if done_qty + EPSILON >= recommended:
        stage = "DONE"
        action_po = _latest_po([po for po, _ in done_rows])
    elif done_qty + finalized_qty + EPSILON >= recommended:
        stage = "READY_TO_SEND"
        action_po = _latest_po([po for po, _ in finalized_rows])
    elif total_qty + EPSILON >= recommended:
        stage = "DRAFT_NEEDS_FINAL"
        action_po = _latest_po([po for po, _ in draft_rows])
    else:
        stage = "OPEN"
        action_po = None

    latest_completed_po = _latest_po([po for po, _ in done_rows])
    return {
        "stage": stage,
        "action_po": action_po,
        "contributors": [po for po, _ in rows],
        "covered_qty": round(total_qty, 4),
        "completed_qty": round(done_qty, 4),
        "finalized_qty": round(finalized_qty, 4),
        "draft_qty": round(draft_qty, 4),
        "latest_completed_po": latest_completed_po,
        "remaining_qty": max(0.0, round(recommended - total_qty, 4)),
    }


def _group_stage(requirement_stages: list[str], po_date: date, target: date) -> str:
    if any(stage == "OPEN" for stage in requirement_stages):
        return _open_status(po_date, target)
    if any(stage == "DRAFT_NEEDS_FINAL" for stage in requirement_stages):
        return "DRAFT_NEEDS_FINAL"
    if any(stage == "READY_TO_SEND" for stage in requirement_stages):
        return "READY_TO_SEND"
    return "DONE"


@router.get("/po-reminders-v4")
def po_reminders_v4(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    target = as_of or date.today()
    horizon_through = target + timedelta(days=horizon_days - 1)
    overdue_from = target - timedelta(days=OVERDUE_LOOKBACK_DAYS)
    normalized_site = site.upper().strip()

    if not database_ready() or (normalized_site and normalized_site not in {"MAJA", "CEMPLANG"}):
        return {
            "date": target,
            "horizonThrough": horizon_through,
            "site": normalized_site or None,
            "dueCount": 0,
            "tomorrowCount": 0,
            "overdueCount": 0,
            "missingLeadTimeCount": 0,
            "items": [],
        }

    scan_until = horizon_through + timedelta(days=MAX_LEAD_DAYS + 2)

    with connection() as conn:
        with conn.cursor() as cur:
            plan_sql = """
                select ps.id snapshot_id, psi.id planning_item_id,
                       upper(ps.site) site, ps.distribution_date,
                       coalesce(date(ps.cooking_at), ps.distribution_date-1) cooking_date,
                       psi.item_name, psi.category_code, psi.preferred_vendor_code,
                       psi.unit, coalesce(psi.planned_qty,0) planned_qty
                from planning_snapshots ps
                join planning_snapshot_items psi on psi.planning_snapshot_id=ps.id
                where ps.status='ACTIVE'
                  and ps.distribution_date between %s and %s
                  and coalesce(psi.planned_qty,0)>0
            """
            plan_params: list[Any] = [target, scan_until]
            if normalized_site:
                plan_sql += " and upper(ps.site)=%s"
                plan_params.append(normalized_site)
            cur.execute(plan_sql, plan_params)
            plans = cur.fetchall()

            cur.execute(
                """
                select vr.*, e.name vendor_name
                from vendor_rules vr
                join entities e on e.code=vr.vendor_code
                where vr.effective_from <= %s
                  and (vr.effective_to is null or vr.effective_to >= %s)
                """,
                (scan_until, overdue_from),
            )
            rules = cur.fetchall()

            cur.execute("select upper(code) code, name from entities where active=true")
            vendor_names = {str(row["code"]).upper(): str(row.get("name") or row["code"]) for row in cur.fetchall()}

            po_sql = """
                select po.id, po.po_code, po.revision_no, upper(po.site) site,
                       upper(po.vendor_code) vendor_code, upper(po.status) status,
                       po.created_at, po.finalized_at, po.sent_at,
                       pc.distribution_date base_distribution_date
                from purchase_orders po
                join production_cycles pc on pc.id=po.production_cycle_id
                where upper(coalesce(po.status,'')) <> all(%s)
                  and (
                    pc.distribution_date between %s and %s
                    or exists (
                      select 1 from purchase_order_coverage poc
                      where poc.purchase_order_id=po.id
                        and poc.distribution_date between %s and %s
                    )
                  )
            """
            po_params: list[Any] = [
                list(INACTIVE_STATUSES),
                target, scan_until,
                target, scan_until,
            ]
            if normalized_site:
                po_sql += " and upper(po.site)=%s"
                po_params.append(normalized_site)
            po_sql += " order by po.created_at desc, po.revision_no desc"
            cur.execute(po_sql, po_params)
            pos = cur.fetchall()

            po_ids = [int(po["id"]) for po in pos]
            direct_items: list[dict[str, Any]] = []
            coverage_items: list[dict[str, Any]] = []
            if po_ids:
                cur.execute(
                    """
                    select poi.purchase_order_id, poi.item_name, poi.po_qty, poi.unit
                    from purchase_order_items poi
                    where poi.purchase_order_id=any(%s)
                      and coalesce(poi.po_qty,0)>0
                    """,
                    (po_ids,),
                )
                direct_items = cur.fetchall()

                cur.execute(
                    """
                    select poc.purchase_order_id, poc.distribution_date,
                           poci.item_name, poci.po_qty, poci.unit
                    from purchase_order_coverage poc
                    join purchase_order_coverage_items poci
                      on poci.purchase_order_coverage_id=poc.id
                    where poc.purchase_order_id=any(%s)
                      and coalesce(poci.po_qty,0)>0
                    """,
                    (po_ids,),
                )
                coverage_items = cur.fetchall()

    candidates: list[dict[str, Any]] = []
    missing_lead_rows: list[dict[str, Any]] = []

    for raw_row in plans:
        row = dict(raw_row)
        vendor, rule, bucket = _resolve_procurement_rule(rules, vendor_names, row)
        if not vendor:
            continue
        if not rule or rule.get("lead_time_days_before_cooking") is None:
            missing_lead_rows.append({
                **row,
                "vendor_code": vendor,
                "vendor_name": vendor_names.get(vendor, vendor),
                "procurement_bucket": bucket,
            })
            continue

        lead = int(rule["lead_time_days_before_cooking"])
        po_date = row["cooking_date"] - timedelta(days=lead)
        if po_date < overdue_from or po_date > horizon_through:
            continue
        row.update({
            "vendor_code": vendor,
            "vendor_name": rule.get("vendor_name") or vendor_names.get(vendor, vendor),
            "lead_time_days_before_cooking": lead,
            "po_date": po_date,
            "stock_key": _stock_key(row.get("item_name"), row.get("unit")),
            "procurement_bucket": bucket,
        })
        candidates.append(row)

    # Stock projections are independent per (site, distribution date). Previously
    # they were calculated serially and every lookup performs several PostgreSQL
    # queries. A small bounded pool keeps first-hit latency down without opening an
    # unbounded number of Railway database connections.
    projection_keys = sorted({(row["site"], row["distribution_date"]) for row in candidates})
    projection_cache: dict[tuple[str, date], tuple[dict[tuple[str, str], float], str]] = {}
    if projection_keys:
        worker_count = min(PROJECTION_WORKERS, len(projection_keys))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="po-projection") as executor:
            futures = {executor.submit(_projection_lookup, *key): key for key in projection_keys}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    projection_cache[key] = future.result()
                except Exception:
                    projection_cache[key] = ({}, "PROJECTION_UNAVAILABLE")

    requirements: dict[tuple[str, str, date, date, str, str, str], dict[str, Any]] = {}

    for row in candidates:
        projection_key = (row["site"], row["distribution_date"])
        stock_lookup, projection_basis = projection_cache.get(
            projection_key,
            ({}, "PROJECTION_UNAVAILABLE"),
        )
        available = float(stock_lookup.get(row["stock_key"], 0.0))
        planned = max(0.0, float(row.get("planned_qty") or 0))
        if planned - available <= EPSILON:
            continue

        type_code, unit = row["stock_key"]
        req_key = (
            row["site"], row["vendor_code"], row["po_date"], row["distribution_date"],
            type_code, unit, row["procurement_bucket"],
        )
        req = requirements.setdefault(req_key, {
            "site": row["site"],
            "vendor_code": row["vendor_code"],
            "vendor_name": row["vendor_name"],
            "po_date": row["po_date"],
            "distribution_date": row["distribution_date"],
            "lead_time_days_before_cooking": row["lead_time_days_before_cooking"],
            "procurement_bucket": row["procurement_bucket"],
            "type_code": type_code,
            "unit": unit,
            "cooking_dates": set(),
            "item_names": set(),
            "families": set(),
            "planned_qty": 0.0,
            "projected_stock_qty": available,
            "recommended_po_qty": 0.0,
            "projection_basis": projection_basis,
        })
        req["cooking_dates"].add(row["cooking_date"])
        req["item_names"].add(str(row.get("item_name") or "").strip())
        req["families"].add(item_family(row.get("item_name"), row.get("category_code")))
        req["planned_qty"] = round(float(req["planned_qty"]) + planned, 4)
        req["projected_stock_qty"] = max(float(req["projected_stock_qty"]), available)
        req["recommended_po_qty"] = max(
            0.0,
            round(float(req["planned_qty"]) - float(req["projected_stock_qty"]), 4),
        )

    po_by_id = {int(po["id"]): po for po in pos}
    coverage_po_ids = {int(item["purchase_order_id"]) for item in coverage_items}
    exact_qty: dict[tuple[int, date, str, str], float] = {}

    for item in direct_items:
        po_id = int(item["purchase_order_id"])
        if po_id in coverage_po_ids:
            # For a PO with explicit per-date coverage, only coverage rows may
            # satisfy reminder requirements; aggregated header items are not dated.
            continue
        distribution_date = po_by_id[po_id].get("base_distribution_date")
        if not distribution_date:
            continue
        type_code, unit = _stock_key(item.get("item_name"), item.get("unit"))
        key = (po_id, distribution_date, type_code, unit)
        exact_qty[key] = round(exact_qty.get(key, 0.0) + float(item.get("po_qty") or 0), 4)

    for item in coverage_items:
        po_id = int(item["purchase_order_id"])
        type_code, unit = _stock_key(item.get("item_name"), item.get("unit"))
        key = (po_id, item["distribution_date"], type_code, unit)
        exact_qty[key] = round(exact_qty.get(key, 0.0) + float(item.get("po_qty") or 0), 4)

    active_pos = [po for po in pos if str(po.get("status") or "").upper() not in INACTIVE_STATUSES]
    grouped: dict[tuple[str, str, date, str], dict[str, Any]] = {}

    for req in requirements.values():
        group_key = (
            req["site"], req["vendor_code"], req["po_date"], req["procurement_bucket"],
        )
        group = grouped.setdefault(group_key, {
            "site": req["site"],
            "vendor_code": req["vendor_code"],
            "vendor_name": req["vendor_name"],
            "po_date": req["po_date"],
            "procurement_bucket": req["procurement_bucket"],
            "lead_time_days_before_cooking": req["lead_time_days_before_cooking"],
            "requirements": [],
        })
        group["requirements"].append(req)

    items: list[dict[str, Any]] = []

    for group in grouped.values():
        relevant_pos = [
            po for po in active_pos
            if po["site"] == group["site"] and po["vendor_code"] == group["vendor_code"]
        ]
        requirement_details: list[dict[str, Any]] = []
        requirement_stages: list[str] = []
        action_candidates: list[dict[str, Any]] = []
        partial_pos: dict[int, dict[str, Any]] = {}
        missing_item_names: set[str] = set()
        missing_distribution_dates: set[date] = set()

        for req in group["requirements"]:
            coverage = _coverage_stage(
                relevant_pos,
                exact_qty,
                req["distribution_date"],
                req["type_code"],
                req["unit"],
                float(req["recommended_po_qty"]),
            )
            requirement_stages.append(coverage["stage"])
            if coverage["action_po"]:
                action_candidates.append(coverage["action_po"])
            for po in coverage["contributors"]:
                partial_pos[int(po["id"])] = po

            names = sorted(name for name in req["item_names"] if name)
            if coverage["remaining_qty"] > EPSILON:
                missing_item_names.update(names)
                missing_distribution_dates.add(req["distribution_date"])

            latest_completed_po = coverage.get("latest_completed_po") or {}
            if coverage["remaining_qty"] <= EPSILON:
                ordering_state = "COVERED"
            elif coverage.get("completed_qty", 0.0) > EPSILON:
                ordering_state = "ORDERED_PARTIAL"
            elif coverage.get("covered_qty", 0.0) > EPSILON:
                ordering_state = "IN_APP_PARTIAL"
            else:
                ordering_state = "NOT_ORDERED"

            requirement_details.append({
                "distribution_date": req["distribution_date"],
                "cooking_dates": sorted(req["cooking_dates"]),
                "item_names": names,
                "item_families": sorted(req["families"]),
                "stock_type_code": req["type_code"],
                "unit": req["unit"] or None,
                "planned_qty": round(float(req["planned_qty"]), 4),
                "projected_stock_qty": round(float(req["projected_stock_qty"]), 4),
                "recommended_po_qty": round(float(req["recommended_po_qty"]), 4),
                "covered_po_qty": coverage["covered_qty"],
                "completed_po_qty": coverage.get("completed_qty", 0.0),
                "finalized_po_qty": coverage.get("finalized_qty", 0.0),
                "draft_po_qty": coverage.get("draft_qty", 0.0),
                "remaining_po_qty": coverage["remaining_qty"],
                "coverage_stage": coverage["stage"],
                "ordering_state": ordering_state,
                "completed_purchase_order_id": latest_completed_po.get("id"),
                "completed_po_code": latest_completed_po.get("po_code"),
                "completed_po_status": latest_completed_po.get("status"),
                "completed_po_created_at": latest_completed_po.get("created_at"),
                "completed_po_sent_at": latest_completed_po.get("sent_at"),
                "projection_basis": req["projection_basis"],
            })

        status = _group_stage(requirement_stages, group["po_date"], target)
        # A PO is exposed in the main PO column only when it fully resolves the
        # reminder state (DONE/READY/DRAFT). Partial/wrong-date POs never masquerade
        # as the PO for an open/overdue/upcoming requirement.
        action_po = None if status in {"OVERDUE", "DUE_TODAY", "UPCOMING"} else _latest_po(action_candidates)

        distribution_dates = sorted({req["distribution_date"] for req in group["requirements"]})
        cooking_dates = sorted({d for req in group["requirements"] for d in req["cooking_dates"]})
        item_names = sorted({name for req in group["requirements"] for name in req["item_names"] if name})
        families = sorted({family for req in group["requirements"] for family in req["families"]})
        partial_codes = sorted({str(po.get("po_code")) for po in partial_pos.values() if po.get("po_code")})

        items.append({
            **{k: v for k, v in group.items() if k != "requirements"},
            "distribution_date": distribution_dates[0] if distribution_dates else None,
            "distribution_dates": distribution_dates,
            "coverage_dates": distribution_dates,
            "cooking_date": cooking_dates[0] if cooking_dates else None,
            "cooking_dates": cooking_dates,
            "item_names": item_names,
            "item_families": families,
            "item_count": len(item_names),
            "requirement_details": requirement_details,
            "missing_item_names": sorted(missing_item_names),
            "missing_distribution_dates": sorted(missing_distribution_dates),
            "partial_po_count": len(partial_pos) if status in {"OVERDUE", "DUE_TODAY", "UPCOMING"} else 0,
            "partial_po_codes": partial_codes if status in {"OVERDUE", "DUE_TODAY", "UPCOMING"} else [],
            "purchase_order_id": action_po.get("id") if action_po else None,
            "po_code": action_po.get("po_code") if action_po else None,
            "po_status": action_po.get("status") if action_po else None,
            "po_created_at": action_po.get("created_at") if action_po else None,
            "po_sent_at": action_po.get("sent_at") if action_po else None,
            "reminder_status": status,
        })

    # Missing lead-time requirements remain visible as data-quality actions instead
    # of disappearing from the reminder engine.
    missing_groups: dict[tuple[str, str, date, str], dict[str, Any]] = {}
    for row in missing_lead_rows:
        key = (row["site"], row["vendor_code"], row["distribution_date"], row["procurement_bucket"])
        group = missing_groups.setdefault(key, {
            "site": row["site"],
            "vendor_code": row["vendor_code"],
            "vendor_name": row["vendor_name"],
            "distribution_date": row["distribution_date"],
            "distribution_dates": {row["distribution_date"]},
            "cooking_dates": set(),
            "item_names": set(),
            "item_families": set(),
            "procurement_bucket": row["procurement_bucket"],
        })
        group["cooking_dates"].add(row["cooking_date"])
        group["item_names"].add(str(row.get("item_name") or "").strip())
        group["item_families"].add(item_family(row.get("item_name"), row.get("category_code")))

    for group in missing_groups.values():
        cooking_dates = sorted(group["cooking_dates"])
        item_names = sorted(name for name in group["item_names"] if name)
        items.append({
            "site": group["site"],
            "vendor_code": group["vendor_code"],
            "vendor_name": group["vendor_name"],
            "po_date": None,
            "lead_time_days_before_cooking": None,
            "procurement_bucket": group["procurement_bucket"],
            "distribution_date": group["distribution_date"],
            "distribution_dates": sorted(group["distribution_dates"]),
            "coverage_dates": [],
            "cooking_date": cooking_dates[0] if cooking_dates else None,
            "cooking_dates": cooking_dates,
            "item_names": item_names,
            "item_families": sorted(group["item_families"]),
            "item_count": len(item_names),
            "requirement_details": [],
            "missing_item_names": item_names,
            "missing_distribution_dates": [group["distribution_date"]],
            "partial_po_count": 0,
            "partial_po_codes": [],
            "purchase_order_id": None,
            "po_code": None,
            "po_status": None,
            "po_created_at": None,
            "po_sent_at": None,
            "reminder_status": "LEAD_TIME_MISSING",
        })

    items.sort(
        key=lambda x: (
            x.get("po_date") is None,
            x.get("po_date") or date.max,
            x.get("vendor_name") or "",
            x.get("procurement_bucket") or "",
        )
    )

    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    tomorrow = target + timedelta(days=1)
    return {
        "date": target,
        "horizonThrough": horizon_through,
        "site": normalized_site or None,
        "dueCount": sum(
            1 for item in items
            if item.get("po_date") is not None
            and item["po_date"] <= target
            and item["reminder_status"] in actionable
        ),
        "tomorrowCount": sum(
            1 for item in items
            if item.get("po_date") == tomorrow and item["reminder_status"] != "DONE"
        ),
        "overdueCount": sum(
            1 for item in items
            if item.get("po_date") is not None
            and item["po_date"] < target
            and item["reminder_status"] == "OVERDUE"
        ),
        "missingLeadTimeCount": len(missing_lead_rows),
        "stockProjectionDates": len(projection_cache),
        "items": items,
    }
