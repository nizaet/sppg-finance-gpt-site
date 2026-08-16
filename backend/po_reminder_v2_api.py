from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection, database_ready

router = APIRouter(tags=["po-reminder-v2"])


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def _semantic_vendor(item: dict[str, Any], site: str) -> str | None:
    category = str(item.get("category_code") or "").lower()
    name = str(item.get("item_name") or "").lower()
    text = f"{category} {name}"
    if re.search(r"\b(ayam|chicken)\b", text):
        return "WIKIAN"
    if re.search(r"\b(dori|ikan|fish)\b", text):
        return "RUMAH_DUTA_PANGAN"
    if re.search(r"\bberas\b", text):
        return "DEDE"
    if re.search(r"\b(gas|lpg)\b", text):
        return "HERU"
    if re.search(r"\btelur\b", text):
        return "KOPERASI"
    if re.search(r"\btahu\b", text):
        return "HAJI_BADRI" if site == "CEMPLANG" else "KOPERASI"
    if re.search(r"\btempe\b", text):
        return "KOPERASI" if site == "MAJA" else None
    if re.search(r"(bahan kering|sembako|dry goods|packaging)", category):
        return "KOPERASI"
    if re.search(r"(sayur|buah|bumbu|vegetable|fruit)", category):
        return "HOLIL"
    return None


def _planned_vendor(item: dict[str, Any], site: str) -> str | None:
    """Resolve the reminder vendor without trusting stale dedicated-vendor hints.

    Dedicated vendors have a narrow product scope.  A stale preferred vendor in
    an older planning snapshot must not create a false reminder (e.g. HAJI_BADRI
    when there is no tahu, or RUMAH_DUTA_PANGAN when there is no fish).
    Broader/manual vendor hints remain usable when they do not contradict the
    product semantics.
    """
    semantic = _semantic_vendor(item, site)
    preferred = str(item.get("preferred_vendor_code") or "").upper().strip()
    if not preferred:
        return semantic

    dedicated = {
        "WIKIAN": "WIKIAN",
        "RUMAH_DUTA_PANGAN": "RUMAH_DUTA_PANGAN",
        "DEDE": "DEDE",
        "HERU": "HERU",
        "HAJI_BADRI": "HAJI_BADRI",
    }
    if preferred in dedicated:
        # Only accept a dedicated vendor when the current item's own category/name
        # resolves to that same vendor.  Otherwise treat the hint as stale.
        return preferred if semantic == dedicated[preferred] else semantic

    # HOLIL/KOPERASI can legitimately cover broader families and manual mappings.
    # If product semantics are known, prefer them over a contradictory old hint.
    return semantic or preferred


def _family_match(vendor: str, rule_category: Any, item_category: Any, item_name: Any) -> bool:
    rc = _norm(rule_category)
    ic = _norm(item_category)
    text = f"{ic}_{_norm(item_name)}"
    if not rc:
        return True
    if rc == ic:
        return True
    if vendor == "HOLIL":
        return "SAYUR" in rc or "BUAH" in rc or "BUMBU" in rc
    if vendor == "WIKIAN":
        return "AYAM" in rc
    if vendor == "RUMAH_DUTA_PANGAN":
        return "IKAN" in rc or "DORI" in rc
    if vendor == "DEDE":
        return "BERAS" in rc
    if vendor == "HERU":
        return "GAS" in rc or "LPG" in rc
    if vendor == "HAJI_BADRI":
        return "TAHU" in rc
    if vendor == "KOPERASI":
        if "TELUR" in text:
            return "TELUR" in rc
        if "TEMPE" in text or "TAHU" in text:
            return "TEMPE" in rc or "TAHU" in rc
        return "BAHAN_KERING" in rc or "KERING" in rc
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


@router.get("/po-reminders-v2")
def po_reminders_v2(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, alias="horizonDays"),
) -> dict[str, Any]:
    target = as_of or date.today()
    tomorrow = target + timedelta(days=1)
    normalized_site = site.upper().strip()
    if not database_ready() or (
        normalized_site and normalized_site not in {"MAJA", "CEMPLANG"}
    ):
        return {
            "date": target,
            "horizonThrough": tomorrow,
            "site": normalized_site or None,
            "dueCount": 0,
            "tomorrowCount": 0,
            "items": [],
        }

    # The action window remains today + tomorrow, while planning is scanned far
    # enough ahead to resolve H-1/H-2/H-3 vendor lead times.
    scan_until = target + timedelta(days=35)
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select upper(ps.site) site,ps.distribution_date,
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

            # A range PO may have its production-cycle date before today's action
            # window but still cover a future distribution date. Include it when
            # either its base cycle OR any explicit coverage date is in the scan.
            po_sql = """
                select po.id,po.po_code,po.revision_no,upper(po.site) site,
                       upper(po.vendor_code) vendor_code,upper(po.status) status,
                       po.created_at,po.finalized_at,po.sent_at,
                       coalesce(
                         (select array_agg(c.distribution_date order by c.distribution_date)
                          from purchase_order_coverage c where c.purchase_order_id=po.id),
                         array[pc.distribution_date]
                       ) coverage_dates
                from purchase_orders po
                join production_cycles pc on pc.id=po.production_cycle_id
                where (
                    pc.distribution_date between %s and %s
                    or exists (
                        select 1 from purchase_order_coverage c
                        where c.purchase_order_id=po.id
                          and c.distribution_date between %s and %s
                    )
                )
            """
            po_params: list[Any] = [target, scan_until, target, scan_until]
            if normalized_site:
                po_sql += " and upper(po.site)=%s"
                po_params.append(normalized_site)
            po_sql += " order by po.created_at desc,po.revision_no desc"
            cur.execute(po_sql, po_params)
            pos = cur.fetchall()

    existing: dict[tuple[str, str, date], dict[str, Any]] = {}
    for po in pos:
        if po["status"] in {"CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"}:
            continue
        for covered_date in po.get("coverage_dates") or []:
            existing.setdefault(
                (po["site"], po["vendor_code"], covered_date),
                po,
            )

    grouped: dict[tuple[str, str, date], dict[str, Any]] = {}
    for row in plans:
        vendor = _planned_vendor(row, row["site"])
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
                "item_count": 0,
            },
        )
        group["distribution_dates"].add(row["distribution_date"])
        group["cooking_dates"].add(row["cooking_date"])
        group["item_names"].add(str(row.get("item_name") or "").strip())
        group["item_count"] += 1

    done = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
    items: list[dict[str, Any]] = []
    for group in grouped.values():
        distributions = sorted(group.pop("distribution_dates"))
        cooks = sorted(group.pop("cooking_dates"))
        item_names = sorted(name for name in group.pop("item_names") if name)
        linked: list[dict[str, Any]] = []
        missing: list[date] = []

        for distribution_date in distributions:
            po = existing.get(
                (group["site"], group["vendor_code"], distribution_date)
            )
            if po:
                linked.append(po)
            else:
                missing.append(distribution_date)

        unique = {int(po["id"]): po for po in linked}
        po_list = list(unique.values())
        statuses = {po["status"] for po in po_list}

        if missing:
            status = "DUE_TODAY" if group["po_date"] == target else "UPCOMING"
            action_po = None
        elif statuses and statuses.issubset(done):
            status = "DONE"
            action_po = po_list[0] if po_list else None
        elif "FINALIZED" in statuses:
            status = "READY_TO_SEND"
            action_po = next(po for po in po_list if po["status"] == "FINALIZED")
        elif "DRAFT" in statuses:
            status = "DRAFT_NEEDS_FINAL"
            action_po = next(po for po in po_list if po["status"] == "DRAFT")
        else:
            status = "DUE_TODAY" if group["po_date"] == target else "UPCOMING"
            action_po = po_list[0] if po_list else None

        items.append(
            {
                **group,
                "distribution_date": distributions[0] if distributions else None,
                "distribution_dates": distributions,
                "coverage_dates": distributions,
                "cooking_date": cooks[0] if cooks else None,
                "cooking_dates": cooks,
                "item_names": item_names,
                "missing_distribution_dates": missing,
                "existing_po_count": len(po_list),
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
            1
            for x in items
            if x["po_date"] == target and x["reminder_status"] in actionable
        ),
        "tomorrowCount": sum(
            1
            for x in items
            if x["po_date"] == tomorrow
            and x["reminder_status"] in actionable | {"UPCOMING"}
        ),
        "items": items,
    }
