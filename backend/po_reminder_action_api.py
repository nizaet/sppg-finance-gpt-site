from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection, database_ready
from backend.item_taxonomy import item_family, vendor_for_item
from backend.po_reminder_v2_api import _rule_for_item

router = APIRouter(tags=["po-reminder-action"])

DONE_STATUSES = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
INACTIVE_STATUSES = {"CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"}


def _prefer_po(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    current_key = (str(current.get("created_at") or ""), int(current.get("revision_no") or 0))
    candidate_key = (str(candidate.get("created_at") or ""), int(candidate.get("revision_no") or 0))
    return candidate if candidate_key >= current_key else current


def _status_for_po(po: dict[str, Any] | None, due_date: date, action_date: date | None) -> str | None:
    if not po:
        return None
    status = str(po.get("status") or "").upper()
    if status in DONE_STATUSES:
        return "DONE"
    if status == "FINALIZED":
        return "READY_TO_SEND"
    if status == "DRAFT":
        return "DRAFT_NEEDS_FINAL"
    return None


@router.get("/po-reminders-v2")
def po_reminders_action(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, alias="horizonDays"),
) -> dict[str, Any]:
    """Two-day PO action checklist.

    The reminder answers a simple operational question: "which vendor still needs
    a PO action on this order date?"  Exact planning-item/coverage links are used
    first.  For *today only*, a real PO action for the same site+vendor today is
    accepted as evidence that the operator already did the work, even when an
    older PO stored an imperfect distribution/cooking coverage date.  That loose
    fallback never suppresses tomorrow's reminder; tomorrow is completed early
    only through an exact planning/snapshot/coverage match.
    """
    target = as_of or date.today()
    tomorrow = target + timedelta(days=1)
    normalized_site = site.upper().strip()
    if not database_ready() or (normalized_site and normalized_site not in {"MAJA", "CEMPLANG"}):
        return {
            "date": target,
            "horizonThrough": tomorrow,
            "site": normalized_site or None,
            "dueCount": 0,
            "tomorrowCount": 0,
            "items": [],
        }

    scan_until = target + timedelta(days=35)
    with connection() as conn:
        with conn.cursor() as cur:
            plan_sql = """
                select ps.id snapshot_id,psi.id planning_item_id,
                       upper(ps.site) site,ps.distribution_date,
                       coalesce(date(ps.cooking_at),ps.distribution_date-1) cooking_date,
                       psi.item_name,psi.category_code,psi.preferred_vendor_code,
                       coalesce(psi.planned_qty,0) planned_qty
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
                select vr.*,e.name vendor_name
                from vendor_rules vr
                join entities e on e.code=vr.vendor_code
                where vr.effective_from <= %s
                  and (vr.effective_to is null or vr.effective_to >= %s)
                """,
                (scan_until, target),
            )
            rules = cur.fetchall()

            po_sql = """
                select po.id,po.po_code,po.revision_no,upper(po.site) site,
                       upper(po.vendor_code) vendor_code,upper(po.status) status,
                       po.created_at,po.finalized_at,po.sent_at,
                       po.source_planning_snapshot_id,
                       pc.distribution_date base_distribution_date,
                       date(pc.cooking_at) base_cooking_date,
                       (coalesce(po.sent_at,po.finalized_at,po.created_at) at time zone 'Asia/Jakarta')::date action_date,
                       coalesce(
                         (select array_agg(c.distribution_date order by c.distribution_date)
                          from purchase_order_coverage c where c.purchase_order_id=po.id),
                         array[pc.distribution_date]
                       ) coverage_dates,
                       coalesce(
                         (select array_agg(distinct c.cooking_date order by c.cooking_date)
                          from purchase_order_coverage c
                          where c.purchase_order_id=po.id and c.cooking_date is not null),
                         array[]::date[]
                       ) coverage_cooking_dates,
                       coalesce(
                         (select array_agg(distinct c.planning_snapshot_id)
                          from purchase_order_coverage c
                          where c.purchase_order_id=po.id and c.planning_snapshot_id is not null),
                         array[]::bigint[]
                       ) coverage_snapshot_ids
                from purchase_orders po
                join production_cycles pc on pc.id=po.production_cycle_id
                where (
                    pc.distribution_date between %s and %s
                    or exists (
                        select 1 from purchase_order_coverage c
                        where c.purchase_order_id=po.id
                          and c.distribution_date between %s and %s
                    )
                    or (coalesce(po.sent_at,po.finalized_at,po.created_at) at time zone 'Asia/Jakarta')::date between %s and %s
                )
            """
            po_params: list[Any] = [
                target - timedelta(days=7), scan_until,
                target - timedelta(days=7), scan_until,
                target - timedelta(days=7), tomorrow,
            ]
            if normalized_site:
                po_sql += " and upper(po.site)=%s"
                po_params.append(normalized_site)
            po_sql += " order by po.created_at desc,po.revision_no desc"
            cur.execute(po_sql, po_params)
            pos = cur.fetchall()

            po_ids = [int(po["id"]) for po in pos]
            po_plan_items: dict[int, set[int]] = {po_id: set() for po_id in po_ids}
            if po_ids:
                cur.execute(
                    """
                    select purchase_order_id,planning_snapshot_item_id
                    from purchase_order_items
                    where purchase_order_id=any(%s)
                      and planning_snapshot_item_id is not null
                    """,
                    (po_ids,),
                )
                for row in cur.fetchall():
                    po_plan_items[int(row["purchase_order_id"])].add(int(row["planning_snapshot_item_id"]))

                cur.execute(
                    """
                    select poc.purchase_order_id,poci.planning_snapshot_item_id
                    from purchase_order_coverage poc
                    join purchase_order_coverage_items poci on poci.purchase_order_coverage_id=poc.id
                    where poc.purchase_order_id=any(%s)
                      and poci.planning_snapshot_item_id is not null
                    """,
                    (po_ids,),
                )
                for row in cur.fetchall():
                    po_plan_items[int(row["purchase_order_id"])].add(int(row["planning_snapshot_item_id"]))

    active_pos: list[dict[str, Any]] = []
    for po in pos:
        if str(po.get("status") or "").upper() in INACTIVE_STATUSES:
            continue
        po_id = int(po["id"])
        po["planning_item_ids"] = po_plan_items.get(po_id, set())
        snapshot_ids = set(int(x) for x in (po.get("coverage_snapshot_ids") or []) if x is not None)
        if po.get("source_planning_snapshot_id") is not None:
            snapshot_ids.add(int(po["source_planning_snapshot_id"]))
        po["planning_snapshot_ids"] = snapshot_ids
        active_pos.append(po)

    by_plan_item: dict[int, dict[str, Any]] = {}
    by_snapshot_vendor: dict[tuple[int, str], dict[str, Any]] = {}
    by_vendor_distribution: dict[tuple[str, str, date], dict[str, Any]] = {}
    by_vendor_cooking: dict[tuple[str, str, date], dict[str, Any]] = {}
    by_vendor_action_date: dict[tuple[str, str, date], dict[str, Any]] = {}

    for po in active_pos:
        for planning_item_id in po["planning_item_ids"]:
            by_plan_item[planning_item_id] = _prefer_po(by_plan_item.get(planning_item_id), po)
        for snapshot_id in po["planning_snapshot_ids"]:
            key = (snapshot_id, po["vendor_code"])
            by_snapshot_vendor[key] = _prefer_po(by_snapshot_vendor.get(key), po)
        for distribution_date in po.get("coverage_dates") or [po.get("base_distribution_date")]:
            if distribution_date:
                key = (po["site"], po["vendor_code"], distribution_date)
                by_vendor_distribution[key] = _prefer_po(by_vendor_distribution.get(key), po)
        cooking_dates = [x for x in (po.get("coverage_cooking_dates") or []) if x]
        if po.get("base_cooking_date"):
            cooking_dates.append(po["base_cooking_date"])
        for cooking_date in cooking_dates:
            key = (po["site"], po["vendor_code"], cooking_date)
            by_vendor_cooking[key] = _prefer_po(by_vendor_cooking.get(key), po)
        action_date = po.get("action_date")
        if action_date:
            key = (po["site"], po["vendor_code"], action_date)
            by_vendor_action_date[key] = _prefer_po(by_vendor_action_date.get(key), po)

    grouped: dict[tuple[str, str, date], dict[str, Any]] = {}
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
        if po_date not in {target, tomorrow}:
            continue

        key = (row["site"], vendor, po_date)
        group = grouped.setdefault(
            key,
            {
                "site": row["site"],
                "vendor_code": vendor,
                "vendor_name": rule.get("vendor_name") or vendor,
                "po_date": po_date,
                "lead_time_days_before_cooking": lead,
                "distribution_dates": set(),
                "cooking_dates": set(),
                "item_names": set(),
                "families": set(),
                "rows": [],
            },
        )
        group["distribution_dates"].add(row["distribution_date"])
        group["cooking_dates"].add(row["cooking_date"])
        group["item_names"].add(str(row.get("item_name") or "").strip())
        group["families"].add(item_family(row.get("item_name"), row.get("category_code")))
        group["rows"].append(row)

    items: list[dict[str, Any]] = []
    for group in grouped.values():
        distributions = sorted(group.pop("distribution_dates"))
        cooks = sorted(group.pop("cooking_dates"))
        item_names = sorted(name for name in group.pop("item_names") if name)
        families = sorted(group.pop("families"))
        rows = group.pop("rows")

        linked: dict[int, dict[str, Any]] = {}
        missing_rows: list[dict[str, Any]] = []
        match_methods: set[str] = set()
        for row in rows:
            planning_item_id = int(row["planning_item_id"])
            snapshot_id = int(row["snapshot_id"])
            po = by_plan_item.get(planning_item_id)
            method = "planning_item_id" if po else ""
            if not po:
                po = by_snapshot_vendor.get((snapshot_id, group["vendor_code"]))
                method = "planning_snapshot" if po else ""
            if not po:
                po = by_vendor_distribution.get((group["site"], group["vendor_code"], row["distribution_date"]))
                method = "vendor_distribution" if po else ""
            if not po:
                po = by_vendor_cooking.get((group["site"], group["vendor_code"], row["cooking_date"]))
                method = "vendor_cooking" if po else ""
            if po:
                linked[int(po["id"])] = po
                match_methods.add(method)
            else:
                missing_rows.append(row)

        po_list = list(linked.values())
        action_po = None
        if po_list:
            action_po = max(
                po_list,
                key=lambda po: (str(po.get("created_at") or ""), int(po.get("revision_no") or 0)),
            )

        all_exact = bool(rows) and not missing_rows
        status: str | None = None
        coverage_warning = False

        if all_exact and action_po:
            statuses = {str(po.get("status") or "").upper() for po in po_list}
            if statuses and statuses.issubset(DONE_STATUSES):
                status = "DONE"
            elif "FINALIZED" in statuses:
                status = "READY_TO_SEND"
                action_po = next((po for po in po_list if str(po.get("status") or "").upper() == "FINALIZED"), action_po)
            elif "DRAFT" in statuses:
                status = "DRAFT_NEEDS_FINAL"
                action_po = next((po for po in po_list if str(po.get("status") or "").upper() == "DRAFT"), action_po)

        # Operational fallback: today's checklist is satisfied by a real PO action
        # for the same site+vendor today. This fixes legacy/misaligned coverage
        # dates without allowing today's PO to suppress tomorrow's separate task.
        if group["po_date"] == target and (status is None or missing_rows):
            same_day_po = by_vendor_action_date.get((group["site"], group["vendor_code"], target))
            same_day_status = _status_for_po(same_day_po, target, target)
            if same_day_po and same_day_status:
                action_po = same_day_po
                status = same_day_status
                coverage_warning = bool(missing_rows) or not all_exact
                match_methods.add("vendor_action_date")

        if status is None:
            status = "DUE_TODAY" if group["po_date"] == target else "UPCOMING"

        missing_item_names = sorted({str(row.get("item_name") or "").strip() for row in missing_rows if row.get("item_name")})
        missing_distribution_dates = sorted({row["distribution_date"] for row in missing_rows})
        completed_early = bool(
            group["po_date"] == tomorrow
            and status == "DONE"
            and action_po
            and action_po.get("action_date")
            and action_po["action_date"] < tomorrow
        )

        items.append(
            {
                **group,
                "distribution_date": distributions[0] if distributions else None,
                "distribution_dates": distributions,
                "coverage_dates": distributions,
                "cooking_date": cooks[0] if cooks else None,
                "cooking_dates": cooks,
                "item_names": item_names,
                "item_families": families,
                "item_count": len(rows),
                "missing_item_names": missing_item_names,
                "missing_distribution_dates": missing_distribution_dates,
                "existing_po_count": len(po_list),
                "po_match_methods": sorted(match_methods),
                "coverage_warning": coverage_warning,
                "completed_early": completed_early,
                "purchase_order_id": action_po.get("id") if action_po else None,
                "po_code": action_po.get("po_code") if action_po else None,
                "po_status": action_po.get("status") if action_po else None,
                "po_created_at": action_po.get("created_at") if action_po else None,
                "po_sent_at": action_po.get("sent_at") if action_po else None,
                "po_action_date": action_po.get("action_date") if action_po else None,
                "reminder_status": status,
            }
        )

    items.sort(key=lambda x: (x["po_date"], x["vendor_name"]))
    actionable = {"DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    return {
        "date": target,
        "horizonThrough": tomorrow,
        "site": normalized_site or None,
        "dueCount": sum(1 for x in items if x["po_date"] == target and x["reminder_status"] in actionable),
        "tomorrowCount": sum(
            1 for x in items
            if x["po_date"] == tomorrow and x["reminder_status"] in actionable | {"UPCOMING"}
        ),
        "missingLeadTimeCount": missing_lead_time_count,
        "items": items,
    }
