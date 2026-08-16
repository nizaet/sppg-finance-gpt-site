from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection, database_ready
from backend.item_taxonomy import item_family, vendor_for_item

router = APIRouter(tags=["po-reminder-v2"])


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def _family_match(vendor: str, rule_category: Any, item_category: Any, item_name: Any) -> bool:
    rc = _norm(rule_category)
    ic = _norm(item_category)
    family = item_family(item_name, item_category)
    if not rc:
        return True
    if rc == ic:
        return True
    if vendor == "HOLIL":
        return family == "PRODUCE" and any(token in rc for token in ("SAYUR", "BUAH", "BUMBU"))
    if vendor == "WIKIAN":
        return family == "CHICKEN" and "AYAM" in rc
    if vendor == "RUMAH_DUTA_PANGAN":
        return family == "FISH" and ("IKAN" in rc or "DORI" in rc)
    if vendor == "DEDE":
        return family == "RICE" and "BERAS" in rc
    if vendor == "HERU":
        return family == "GAS" and ("GAS" in rc or "LPG" in rc)
    if vendor == "HAJI_BADRI":
        return family == "TOFU" and "TAHU" in rc
    if vendor == "KOPERASI":
        if family == "EGG":
            return "TELUR" in rc
        if family in {"TEMPE", "TOFU"}:
            return "TEMPE" in rc or "TAHU" in rc
        if family == "DRY_GOODS":
            return "BAHAN_KERING" in rc or "KERING" in rc or "SEMBAKO" in rc
        return False
    return False


def _rule_for_item(
    rules: list[dict[str, Any]],
    vendor: str,
    site: str,
    category: Any,
    item_name: Any,
    cook: date,
) -> dict[str, Any] | None:
    candidates = [
        r
        for r in rules
        if str(r.get("vendor_code") or "").upper() == vendor
        and (r.get("site_code") is None or str(r.get("site_code")).upper() == site)
        and r["effective_from"] <= cook
        and (r.get("effective_to") is None or r["effective_to"] >= cook)
    ]
    scored: list[tuple[int, dict[str, Any]]] = []
    for rule in candidates:
        rc = _norm(rule.get("category_code"))
        score = 10 if rule.get("site_code") is not None else 0
        if rc and rc == _norm(category):
            score += 100
        elif _family_match(vendor, rc, category, item_name):
            score += 80
        elif not rc:
            score += 60
        else:
            continue
        scored.append((score, rule))
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    leads = {
        r.get("lead_time_days_before_cooking")
        for r in candidates
        if r.get("lead_time_days_before_cooking") is not None
    }
    if len(leads) == 1 and candidates:
        candidates.sort(key=lambda r: r.get("site_code") is not None, reverse=True)
        return candidates[0]
    return None


def _prefer_po(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    current_key = (str(current.get("created_at") or ""), int(current.get("revision_no") or 0))
    candidate_key = (str(candidate.get("created_at") or ""), int(candidate.get("revision_no") or 0))
    return candidate if candidate_key >= current_key else current


@router.get("/po-reminders-v2")
def po_reminders_v2(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, alias="horizonDays"),
) -> dict[str, Any]:
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
            sql = """
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
            params: list[Any] = [target, scan_until]
            if normalized_site:
                sql += " and upper(ps.site)=%s"
                params.append(normalized_site)
            cur.execute(sql, params)
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
                    or po.created_at::date between %s and %s
                )
            """
            po_params: list[Any] = [target - timedelta(days=7), scan_until, target - timedelta(days=7), scan_until, target - timedelta(days=7), tomorrow]
            if normalized_site:
                po_sql += " and upper(po.site)=%s"
                po_params.append(normalized_site)
            po_sql += " order by po.created_at desc,po.revision_no desc"
            cur.execute(po_sql, po_params)
            pos = cur.fetchall()

            po_ids = [int(po["id"]) for po in pos]
            po_plan_items: dict[int, set[int]] = {po_id: set() for po_id in po_ids}
            po_item_names: dict[int, set[str]] = {po_id: set() for po_id in po_ids}
            if po_ids:
                cur.execute(
                    """
                    select purchase_order_id,planning_snapshot_item_id,item_name
                    from purchase_order_items
                    where purchase_order_id=any(%s)
                    """,
                    (po_ids,),
                )
                for row in cur.fetchall():
                    po_id = int(row["purchase_order_id"])
                    if row.get("planning_snapshot_item_id") is not None:
                        po_plan_items[po_id].add(int(row["planning_snapshot_item_id"]))
                    if row.get("item_name"):
                        po_item_names[po_id].add(str(row["item_name"]).strip())

                cur.execute(
                    """
                    select poc.purchase_order_id,poci.planning_snapshot_item_id,poci.item_name
                    from purchase_order_coverage poc
                    join purchase_order_coverage_items poci on poci.purchase_order_coverage_id=poc.id
                    where poc.purchase_order_id=any(%s)
                    """,
                    (po_ids,),
                )
                for row in cur.fetchall():
                    po_id = int(row["purchase_order_id"])
                    if row.get("planning_snapshot_item_id") is not None:
                        po_plan_items[po_id].add(int(row["planning_snapshot_item_id"]))
                    if row.get("item_name"):
                        po_item_names[po_id].add(str(row["item_name"]).strip())

    active_pos: list[dict[str, Any]] = []
    for po in pos:
        if po["status"] in {"CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"}:
            continue
        po_id = int(po["id"])
        po["planning_item_ids"] = po_plan_items.get(po_id, set())
        po["item_names"] = po_item_names.get(po_id, set())
        snapshot_ids = set(int(x) for x in (po.get("coverage_snapshot_ids") or []) if x is not None)
        if po.get("source_planning_snapshot_id") is not None:
            snapshot_ids.add(int(po["source_planning_snapshot_id"]))
        po["planning_snapshot_ids"] = snapshot_ids
        active_pos.append(po)

    by_plan_item: dict[int, dict[str, Any]] = {}
    by_snapshot_vendor: dict[tuple[int, str], dict[str, Any]] = {}
    by_vendor_distribution: dict[tuple[str, str, date], dict[str, Any]] = {}
    by_vendor_cooking: dict[tuple[str, str, date], dict[str, Any]] = {}
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

    done = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
    items: list[dict[str, Any]] = []
    for group in grouped.values():
        distributions = sorted(group.pop("distribution_dates"))
        cooks = sorted(group.pop("cooking_dates"))
        item_names = sorted(name for name in group.pop("item_names") if name)
        families = sorted(group.pop("families"))
        rows = group.pop("rows")

        linked: dict[int, dict[str, Any]] = {}
        missing_item_names: list[str] = []
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
                missing_item_names.append(str(row.get("item_name") or "").strip())

        po_list = list(linked.values())
        statuses = {po["status"] for po in po_list}
        action_po = None
        if po_list:
            action_po = max(
                po_list,
                key=lambda po: (str(po.get("created_at") or ""), int(po.get("revision_no") or 0)),
            )

        all_items_covered = not missing_item_names and bool(rows)
        if all_items_covered and statuses and statuses.issubset(done):
            status = "DONE"
        elif all_items_covered and "FINALIZED" in statuses:
            status = "READY_TO_SEND"
            action_po = next((po for po in po_list if po["status"] == "FINALIZED"), action_po)
        elif all_items_covered and "DRAFT" in statuses:
            status = "DRAFT_NEEDS_FINAL"
            action_po = next((po for po in po_list if po["status"] == "DRAFT"), action_po)
        else:
            status = "DUE_TODAY" if group["po_date"] == target else "UPCOMING"

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
                "missing_item_names": sorted(set(x for x in missing_item_names if x)),
                "missing_distribution_dates": sorted({
                    row["distribution_date"]
                    for row in rows
                    if str(row.get("item_name") or "").strip() in missing_item_names
                }),
                "existing_po_count": len(po_list),
                "po_match_methods": sorted(match_methods),
                "purchase_order_id": action_po.get("id") if action_po else None,
                "po_code": action_po.get("po_code") if action_po else None,
                "po_status": action_po.get("status") if action_po else None,
                "po_created_at": action_po.get("created_at") if action_po else None,
                "po_sent_at": action_po.get("sent_at") if action_po else None,
                "reminder_status": status,
            }
        )

    items.sort(key=lambda x: (x["po_date"], x["vendor_name"]))
    actionable = {"DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    return {
        "date": target,
        "horizonThrough": tomorrow,
        "site": normalized_site or None,
        "dueCount": sum(
            1 for x in items
            if x["po_date"] == target and x["reminder_status"] in actionable
        ),
        "tomorrowCount": sum(
            1 for x in items
            if x["po_date"] == tomorrow and x["reminder_status"] in actionable | {"UPCOMING"}
        ),
        "missingLeadTimeCount": missing_lead_time_count,
        "items": items,
    }
