from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection, database_ready
from backend.inventory_projection_v2_api import inventory_balances_v2
from backend.item_taxonomy import item_family, stock_type, vendor_for_item
from backend.po_reminder_v2_api import _rule_for_item
from backend.stock_opname_parser import canonical_unit

router = APIRouter(tags=["po-reminder-v3"])

DONE_STATUSES = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
INACTIVE_STATUSES = {"CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"}
OVERDUE_LOOKBACK_DAYS = 7
MAX_LEAD_DAYS = 30
EPSILON = 0.0001


def _stock_key(name: Any, unit: Any) -> tuple[str, str]:
    typed = stock_type(name)
    return typed["code"], canonical_unit(unit) or ""


def _prefer_po(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    current_key = (str(current.get("created_at") or ""), int(current.get("revision_no") or 0))
    candidate_key = (str(candidate.get("created_at") or ""), int(candidate.get("revision_no") or 0))
    return candidate if candidate_key >= current_key else current


def _status_from_pos(pos: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None]:
    if not pos:
        return None, None
    latest = max(pos, key=lambda po: (str(po.get("created_at") or ""), int(po.get("revision_no") or 0)))
    statuses = {str(po.get("status") or "").upper() for po in pos}
    if statuses and statuses.issubset(DONE_STATUSES):
        return "DONE", latest
    finalized = [po for po in pos if str(po.get("status") or "").upper() == "FINALIZED"]
    if finalized:
        return "READY_TO_SEND", max(finalized, key=lambda po: str(po.get("created_at") or ""))
    drafts = [po for po in pos if str(po.get("status") or "").upper() == "DRAFT"]
    if drafts:
        return "DRAFT_NEEDS_FINAL", max(drafts, key=lambda po: str(po.get("created_at") or ""))
    return None, latest


def _open_status(po_date: date, target: date) -> str:
    if po_date < target:
        return "OVERDUE"
    if po_date == target:
        return "DUE_TODAY"
    return "UPCOMING"


def _projection_lookup(site: str, distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    """Return projected stock available immediately before the target distribution date.

    Projection failure is intentionally fail-open for procurement: the caller then
    treats stock as unknown/zero rather than suppressing a needed PO reminder.
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
        available = max(0.0, float(item.get("available_for_po") or item.get("balance") or 0))
        lookup[key] = max(lookup.get(key, 0.0), available)
    return lookup, str(payload.get("projectionModel") or "INVENTORY_PROJECTION_V2")


@router.get("/po-reminders-v3")
def po_reminders_v3(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Lead-time aware PO action list with projected-stock shortfall checking.

    The action window is based on PO date, not distribution date. H-3/H-5 rules
    therefore become actionable on their true order date. Unfinished order dates
    from the previous seven days remain visible as OVERDUE instead of disappearing.

    A same-day vendor PO may repair legacy/misaligned coverage only when the PO
    actually contains enough of the required ingredient type. Merely sending any
    PO to the same vendor no longer suppresses other items (for example Tempe).
    """
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

    # The PO-date horizon must scan far enough into cooking/distribution dates to
    # include the largest editable lead time (H-30).
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

            po_sql = """
                select po.id, po.po_code, po.revision_no, upper(po.site) site,
                       upper(po.vendor_code) vendor_code, upper(po.status) status,
                       po.created_at, po.finalized_at, po.sent_at,
                       pc.distribution_date base_distribution_date,
                       (coalesce(po.sent_at,po.finalized_at,po.created_at)
                         at time zone 'Asia/Jakarta')::date action_date
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
                    or (coalesce(po.sent_at,po.finalized_at,po.created_at)
                        at time zone 'Asia/Jakarta')::date between %s and %s
                  )
            """
            po_params: list[Any] = [
                list(INACTIVE_STATUSES),
                overdue_from, scan_until,
                overdue_from, scan_until,
                overdue_from, horizon_through,
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

    # Resolve vendor + rule first, then keep only rows whose *PO date* is in the
    # requested action horizon (plus a short overdue safety window).
    candidates: list[dict[str, Any]] = []
    missing_lead_time_count = 0
    for row in plans:
        vendor = vendor_for_item(
            row.get("item_name"),
            row.get("category_code"),
            row["site"],
            row.get("preferred_vendor_code"),
        )
        if not vendor:
            continue
        rule = _rule_for_item(
            rules,
            vendor,
            row["site"],
            row.get("category_code"),
            row.get("item_name"),
            row["cooking_date"],
        )
        if not rule or rule.get("lead_time_days_before_cooking") is None:
            missing_lead_time_count += 1
            continue
        lead = int(rule["lead_time_days_before_cooking"])
        po_date = row["cooking_date"] - timedelta(days=lead)
        if po_date < overdue_from or po_date > horizon_through:
            continue
        candidate = dict(row)
        candidate.update({
            "vendor_code": vendor,
            "vendor_name": rule.get("vendor_name") or vendor,
            "lead_time_days_before_cooking": lead,
            "po_date": po_date,
            "stock_key": _stock_key(row.get("item_name"), row.get("unit")),
        })
        candidates.append(candidate)

    # Stock projection is cached per site + distribution date. The quantity to
    # order is planning minus projected available stock immediately before that
    # distribution date. No matching stock row means zero defensible stock.
    projection_cache: dict[tuple[str, date], tuple[dict[tuple[str, str], float], str]] = {}
    requirements: dict[tuple[str, str, date, date, str, str], dict[str, Any]] = {}
    for row in candidates:
        projection_key = (row["site"], row["distribution_date"])
        if projection_key not in projection_cache:
            projection_cache[projection_key] = _projection_lookup(*projection_key)
        stock_lookup, projection_basis = projection_cache[projection_key]
        available = float(stock_lookup.get(row["stock_key"], 0.0))
        planned = max(0.0, float(row.get("planned_qty") or 0))
        recommended = max(0.0, round(planned - available, 4))
        if recommended <= EPSILON:
            continue

        type_code, unit = row["stock_key"]
        req_key = (
            row["site"], row["vendor_code"], row["po_date"],
            row["distribution_date"], type_code, unit,
        )
        req = requirements.setdefault(
            req_key,
            {
                "site": row["site"],
                "vendor_code": row["vendor_code"],
                "vendor_name": row["vendor_name"],
                "po_date": row["po_date"],
                "distribution_date": row["distribution_date"],
                "cooking_dates": set(),
                "lead_time_days_before_cooking": row["lead_time_days_before_cooking"],
                "type_code": type_code,
                "unit": unit,
                "item_names": set(),
                "families": set(),
                "planned_qty": 0.0,
                "projected_stock_qty": available,
                "recommended_po_qty": 0.0,
                "projection_basis": projection_basis,
            },
        )
        req["cooking_dates"].add(row["cooking_date"])
        req["item_names"].add(str(row.get("item_name") or "").strip())
        req["families"].add(item_family(row.get("item_name"), row.get("category_code")))
        req["planned_qty"] = round(float(req["planned_qty"]) + planned, 4)
        # This mirrors the current PO planner's per-line stock recommendation.
        # Do not subtract the same physical stock again while merging aliases.
        req["projected_stock_qty"] = max(float(req["projected_stock_qty"]), available)
        req["recommended_po_qty"] = max(
            0.0,
            round(float(req["planned_qty"]) - float(req["projected_stock_qty"]), 4),
        )

    po_by_id = {int(po["id"]): po for po in pos}
    coverage_po_ids = {int(item["purchase_order_id"]) for item in coverage_items}
    exact_qty: dict[tuple[int, date, str, str], float] = {}
    aggregate_qty: dict[tuple[int, str, str], float] = {}

    for item in direct_items:
        po_id = int(item["purchase_order_id"])
        type_code, unit = _stock_key(item.get("item_name"), item.get("unit"))
        aggregate_key = (po_id, type_code, unit)
        aggregate_qty[aggregate_key] = round(
            aggregate_qty.get(aggregate_key, 0.0) + float(item.get("po_qty") or 0), 4
        )
        if po_id not in coverage_po_ids:
            distribution_date = po_by_id[po_id].get("base_distribution_date")
            if distribution_date:
                exact_key = (po_id, distribution_date, type_code, unit)
                exact_qty[exact_key] = round(
                    exact_qty.get(exact_key, 0.0) + float(item.get("po_qty") or 0), 4
                )

    for item in coverage_items:
        po_id = int(item["purchase_order_id"])
        type_code, unit = _stock_key(item.get("item_name"), item.get("unit"))
        exact_key = (po_id, item["distribution_date"], type_code, unit)
        exact_qty[exact_key] = round(
            exact_qty.get(exact_key, 0.0) + float(item.get("po_qty") or 0), 4
        )

    active_pos = [po for po in pos if str(po.get("status") or "").upper() not in INACTIVE_STATUSES]
    grouped: dict[tuple[str, str, date], dict[str, Any]] = {}
    for req in requirements.values():
        group_key = (req["site"], req["vendor_code"], req["po_date"])
        group = grouped.setdefault(
            group_key,
            {
                "site": req["site"],
                "vendor_code": req["vendor_code"],
                "vendor_name": req["vendor_name"],
                "po_date": req["po_date"],
                "lead_time_days_before_cooking": req["lead_time_days_before_cooking"],
                "requirements": [],
            },
        )
        group["lead_time_days_before_cooking"] = max(
            int(group["lead_time_days_before_cooking"]),
            int(req["lead_time_days_before_cooking"]),
        )
        group["requirements"].append(req)

    items: list[dict[str, Any]] = []
    for group in grouped.values():
        relevant_pos = [
            po for po in active_pos
            if po["site"] == group["site"] and po["vendor_code"] == group["vendor_code"]
        ]
        used_pos: dict[int, dict[str, Any]] = {}
        coverage_warning = False
        requirement_details: list[dict[str, Any]] = []
        missing_item_names: set[str] = set()
        missing_distribution_dates: set[date] = set()
        all_covered = True

        for req in group["requirements"]:
            type_code = req["type_code"]
            unit = req["unit"]
            distribution_date = req["distribution_date"]
            recommended = float(req["recommended_po_qty"])

            exact_contributors: list[dict[str, Any]] = []
            exact_covered = 0.0
            for po in relevant_pos:
                po_qty = float(exact_qty.get((int(po["id"]), distribution_date, type_code, unit), 0.0))
                if po_qty > EPSILON:
                    exact_covered += po_qty
                    exact_contributors.append(po)

            effective_covered = exact_covered
            contributors = list(exact_contributors)

            # Legacy/misaligned date fallback is allowed only for a PO action on
            # this exact PO date AND only for the same ingredient type+unit.
            # This is the critical guard that prevents an unrelated KOPERASI PO
            # from hiding a new Tempe requirement.
            if effective_covered + EPSILON < recommended and group["po_date"] <= target:
                action_pos = [po for po in relevant_pos if po.get("action_date") == group["po_date"]]
                action_covered = sum(
                    float(aggregate_qty.get((int(po["id"]), type_code, unit), 0.0))
                    for po in action_pos
                )
                if action_covered > effective_covered + EPSILON:
                    effective_covered = action_covered
                    contributors = [
                        po for po in action_pos
                        if float(aggregate_qty.get((int(po["id"]), type_code, unit), 0.0)) > EPSILON
                    ]
                    coverage_warning = True

            for po in contributors:
                used_pos[int(po["id"])] = po

            remaining = max(0.0, round(recommended - effective_covered, 4))
            names = sorted(name for name in req["item_names"] if name)
            if remaining > EPSILON:
                all_covered = False
                missing_item_names.update(names)
                missing_distribution_dates.add(distribution_date)

            requirement_details.append({
                "distribution_date": distribution_date,
                "cooking_dates": sorted(req["cooking_dates"]),
                "item_names": names,
                "item_families": sorted(req["families"]),
                "stock_type_code": type_code,
                "unit": unit or None,
                "planned_qty": round(float(req["planned_qty"]), 4),
                "projected_stock_qty": round(float(req["projected_stock_qty"]), 4),
                "recommended_po_qty": round(recommended, 4),
                "covered_po_qty": round(effective_covered, 4),
                "remaining_po_qty": remaining,
                "projection_basis": req["projection_basis"],
            })

        po_list = list(used_pos.values())
        status: str | None = None
        action_po: dict[str, Any] | None = None
        if all_covered and po_list:
            status, action_po = _status_from_pos(po_list)
        if status is None:
            status = _open_status(group["po_date"], target)
            if relevant_pos:
                action_po = max(
                    relevant_pos,
                    key=lambda po: (str(po.get("created_at") or ""), int(po.get("revision_no") or 0)),
                )

        distribution_dates = sorted({req["distribution_date"] for req in group["requirements"]})
        cooking_dates = sorted({d for req in group["requirements"] for d in req["cooking_dates"]})
        item_names = sorted({name for req in group["requirements"] for name in req["item_names"] if name})
        families = sorted({family for req in group["requirements"] for family in req["families"]})

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
            "existing_po_count": len({int(po["id"]) for po in relevant_pos}),
            "coverage_warning": coverage_warning,
            "purchase_order_id": action_po.get("id") if action_po else None,
            "po_code": action_po.get("po_code") if action_po else None,
            "po_status": action_po.get("status") if action_po else None,
            "po_created_at": action_po.get("created_at") if action_po else None,
            "po_sent_at": action_po.get("sent_at") if action_po else None,
            "po_action_date": action_po.get("action_date") if action_po else None,
            "reminder_status": status,
        })

    items.sort(key=lambda x: (x["po_date"], x["vendor_name"]))
    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    tomorrow = target + timedelta(days=1)
    return {
        "date": target,
        "horizonThrough": horizon_through,
        "site": normalized_site or None,
        "dueCount": sum(
            1 for item in items
            if item["po_date"] <= target and item["reminder_status"] in actionable
        ),
        "tomorrowCount": sum(
            1 for item in items
            if item["po_date"] == tomorrow and item["reminder_status"] != "DONE"
        ),
        "overdueCount": sum(
            1 for item in items
            if item["po_date"] < target and item["reminder_status"] == "OVERDUE"
        ),
        "missingLeadTimeCount": missing_lead_time_count,
        "stockProjectionDates": len(projection_cache),
        "items": items,
    }
