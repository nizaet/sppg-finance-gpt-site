from datetime import date, timedelta
import re
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection, database_ready
from backend.vendor_payables_api import router as vendor_payables_router
from backend.operational_search_api import router as operational_search_router
from backend.operational_history_api import router as operational_history_router
from backend.operations_action_schema_api import router as operations_action_schema_router
from backend.operations_action_schema_fix_api import router as operations_action_schema_fix_router
from backend.operations_action_schema_v017_api import router as operations_action_schema_v017_router
from backend.unified_action_schema_api import router as unified_action_schema_router
from backend.whatsapp_webhook_api import router as whatsapp_webhook_router

router = APIRouter(prefix="/v1", tags=["reference"])
router.include_router(vendor_payables_router)
router.include_router(operational_search_router)
router.include_router(operational_history_router)
router.include_router(operations_action_schema_router)
router.include_router(operations_action_schema_fix_router)
router.include_router(operations_action_schema_v017_router)
router.include_router(unified_action_schema_router)
router.include_router(whatsapp_webhook_router)


@router.get("/schema-status")
def schema_status() -> dict[str, Any]:
    if not database_ready():
        return {"databaseReady": False, "schemaReady": False, "tables": []}
    required = [
        "candidate_events", "workflow_actions", "event_audit_log",
        "production_cycles", "purchase_orders", "vendor_payments",
        "sites", "entities", "vendor_rules", "schema_migrations",
    ]
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select table_name from information_schema.tables
                   where table_schema='public' and table_name = any(%s)""",
                (required,),
            )
            found = sorted(row["table_name"] for row in cur.fetchall())
    return {
        "databaseReady": True,
        "schemaReady": set(required).issubset(found),
        "tables": found,
        "missing": sorted(set(required) - set(found)),
    }


@router.get("/reference/sites")
def reference_sites() -> dict[str, Any]:
    if not database_ready():
        return {"items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select code, name, active from sites where active=true order by code")
            return {"items": cur.fetchall()}


@router.get("/reference/vendors")
def reference_vendors(site: str = "") -> dict[str, Any]:
    if not database_ready():
        return {"items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select e.code, e.name, e.entity_type, e.metadata,
                       vr.site_code, vr.category_code, vr.lead_time_days_before_cooking,
                       vr.payment_term_code, vr.payment_term_payload,
                       vr.internal_reimbursement, vr.intermediary_code,
                       vr.effective_from, vr.effective_to, vr.evidence_ref, vr.notes
                from entities e
                left join vendor_rules vr on vr.vendor_code=e.code
                  and vr.effective_from <= current_date
                  and (vr.effective_to is null or vr.effective_to >= current_date)
                where e.active=true
                  and e.entity_type in ('VENDOR','INTERNAL_ORG')
            """
            params: list[Any] = []
            if site:
                sql += " and (vr.site_code is null or upper(vr.site_code)=upper(%s))"
                params.append(site)
            sql += " order by e.name, vr.site_code, vr.category_code"
            cur.execute(sql, params)
            return {"items": cur.fetchall()}


@router.get("/po-schedule/preview")
def po_schedule_preview(
    distribution_date: date = Query(alias="distributionDate"),
    cooking_date: date | None = Query(default=None, alias="cookingDate"),
    site: str = "",
) -> dict[str, Any]:
    cook = cooking_date or (distribution_date - timedelta(days=1))
    if not database_ready():
        return {"distributionDate": distribution_date, "cookingDate": cook, "items": []}

    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select e.code as vendor_code, e.name as vendor_name,
                       vr.site_code, vr.category_code,
                       vr.lead_time_days_before_cooking,
                       vr.internal_reimbursement, vr.intermediary_code,
                       vr.notes
                from vendor_rules vr
                join entities e on e.code=vr.vendor_code
                where vr.effective_from <= %s
                  and (vr.effective_to is null or vr.effective_to >= %s)
            """
            params: list[Any] = [cook, cook]
            if site:
                sql += " and (vr.site_code is null or upper(vr.site_code)=upper(%s))"
                params.append(site)
            sql += " order by vr.lead_time_days_before_cooking desc nulls last, e.name"
            cur.execute(sql, params)
            rows = cur.fetchall()

    items = []
    for row in rows:
        lead = row["lead_time_days_before_cooking"]
        po_date = cook - timedelta(days=lead) if lead is not None else None
        items.append({**row, "po_date": po_date})
    return {
        "distributionDate": distribution_date.isoformat(),
        "cookingDate": cook.isoformat(),
        "site": site or None,
        "items": items,
    }


def _planned_vendor(item: dict[str, Any], site: str) -> str | None:
    preferred = str(item.get("preferred_vendor_code") or "").upper().strip()
    if preferred:
        return preferred
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


def _reminder_rule_for_item(
    rules: list[dict[str, Any]],
    *,
    vendor: str,
    site: str,
    category: str | None,
    cooking_date: date,
) -> dict[str, Any] | None:
    candidates = [
        rule for rule in rules
        if str(rule["vendor_code"]).upper() == vendor
        and (rule.get("site_code") is None or str(rule["site_code"]).upper() == site)
        and (rule.get("category_code") is None or str(rule["category_code"]).lower() == str(category or "").lower())
        and rule["effective_from"] <= cooking_date
        and (rule.get("effective_to") is None or rule["effective_to"] >= cooking_date)
    ]
    candidates.sort(
        key=lambda rule: (
            rule.get("site_code") is not None,
            rule.get("category_code") is not None,
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


@router.get("/po-reminders")
def po_reminders(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Return PO work due today and tomorrow, grouped by vendor + PO date.

    Planning is scanned farther ahead because a vendor can have H-2/H-3 lead
    time, but the returned action window is intentionally only two PO dates:
    today (H-0) and tomorrow (H+1). Zero-quantity planning lines never create a
    reminder. Missing lead-time rules are excluded from these action boxes
    because they have no defensible PO date.
    """
    target_date = as_of or date.today()
    tomorrow = target_date + timedelta(days=1)
    if not database_ready():
        return {
            "date": target_date,
            "horizonThrough": tomorrow,
            "site": site.upper().strip() or None,
            "dueCount": 0,
            "tomorrowCount": 0,
            "missingLeadTimeCount": 0,
            "items": [],
        }

    normalized_site = site.upper().strip()
    if normalized_site and normalized_site not in {"MAJA", "CEMPLANG"}:
        return {"date": target_date, "horizonThrough": tomorrow, "items": []}

    # The display window is two PO dates, but planning must be scanned farther
    # ahead to catch H-2/H-3 orders whose distribution happens later.
    scan_until = target_date + timedelta(days=max(14, horizon_days + 7))

    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select ps.id as snapshot_id,upper(ps.site) as site,ps.distribution_date,
                       coalesce(date(ps.cooking_at),ps.distribution_date-1) as cooking_date,
                       psi.item_name,psi.category_code,psi.preferred_vendor_code,
                       coalesce(psi.planned_qty,0) as planned_qty
                from planning_snapshots ps
                join planning_snapshot_items psi on psi.planning_snapshot_id=ps.id
                where ps.status='ACTIVE'
                  and ps.distribution_date between %s and %s
                  and coalesce(psi.planned_qty,0) > 0
            """
            params: list[Any] = [target_date, scan_until]
            if normalized_site:
                sql += " and upper(ps.site)=%s"
                params.append(normalized_site)
            cur.execute(sql, params)
            plan_rows = cur.fetchall()

            cur.execute(
                """select vr.*,e.name as vendor_name
                   from vendor_rules vr join entities e on e.code=vr.vendor_code
                   where vr.effective_from <= %s
                     and (vr.effective_to is null or vr.effective_to >= %s)""",
                (scan_until, target_date),
            )
            rules = cur.fetchall()

            po_sql = """
                select po.id,po.po_code,po.revision_no,upper(po.site) as site,
                       upper(po.vendor_code) as vendor_code,upper(po.status) as status,
                       po.created_at,po.finalized_at,po.sent_at,
                       coalesce(poc.distribution_date,pc.distribution_date) as distribution_date,
                       coalesce((select array_agg(c.distribution_date order by c.distribution_date)
                                 from purchase_order_coverage c where c.purchase_order_id=po.id),
                                array[pc.distribution_date]) as coverage_dates
                from purchase_orders po
                join production_cycles pc on pc.id=po.production_cycle_id
                left join purchase_order_coverage poc on poc.purchase_order_id=po.id
                where coalesce(poc.distribution_date,pc.distribution_date) between %s and %s
            """
            po_params: list[Any] = [target_date, scan_until]
            if normalized_site:
                po_sql += " and upper(po.site)=%s"
                po_params.append(normalized_site)
            po_sql += " order by po.created_at desc,po.revision_no desc"
            cur.execute(po_sql, po_params)
            po_rows = cur.fetchall()

    existing: dict[tuple[str, str, date], dict[str, Any]] = {}
    for po in po_rows:
        if po["status"] in {"CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"}:
            continue
        for covered_date in po.get("coverage_dates") or [po["distribution_date"]]:
            key = (po["site"], po["vendor_code"], covered_date)
            if key not in existing:
                existing[key] = po

    grouped: dict[tuple[str, str, date], dict[str, Any]] = {}
    missing_lead_time_count = 0

    for row in plan_rows:
        row_site = row["site"]
        vendor = _planned_vendor(row, row_site)
        if not vendor:
            continue

        cook = row["cooking_date"]
        category = row.get("category_code")
        rule = _reminder_rule_for_item(
            rules,
            vendor=vendor,
            site=row_site,
            category=category,
            cooking_date=cook,
        )
        lead = (
            int(rule["lead_time_days_before_cooking"])
            if rule and rule.get("lead_time_days_before_cooking") is not None
            else None
        )
        if lead is None:
            missing_lead_time_count += 1
            continue

        po_date = cook - timedelta(days=lead)
        if po_date not in {target_date, tomorrow}:
            continue

        key = (row_site, vendor, po_date)
        group = grouped.setdefault(
            key,
            {
                "site": row_site,
                "vendor_code": vendor,
                "vendor_name": rule.get("vendor_name") if rule else vendor,
                "lead_time_days_before_cooking": lead,
                "po_date": po_date,
                "distribution_dates": set(),
                "cooking_dates": set(),
                "item_count": 0,
            },
        )
        group["distribution_dates"].add(row["distribution_date"])
        group["cooking_dates"].add(cook)
        group["item_count"] += 1
        # If mixed categories for one vendor land on the same PO date, retain
        # the longest lead time as the visible safety basis.
        group["lead_time_days_before_cooking"] = max(
            int(group["lead_time_days_before_cooking"]),
            lead,
        )

    done_statuses = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
    items: list[dict[str, Any]] = []

    for _, group in grouped.items():
        distribution_dates = sorted(group.pop("distribution_dates"))
        cooking_dates = sorted(group.pop("cooking_dates"))
        linked: list[dict[str, Any]] = []
        missing_dates: list[date] = []

        for distribution_date in distribution_dates:
            po = existing.get((group["site"], group["vendor_code"], distribution_date))
            if po:
                linked.append(po)
            else:
                missing_dates.append(distribution_date)

        unique_pos: dict[int, dict[str, Any]] = {}
        for po in linked:
            unique_pos[int(po["id"])] = po
        po_list = list(unique_pos.values())
        statuses = {str(po.get("status") or "").upper() for po in po_list}

        action_po = None
        for wanted in ("FINALIZED", "DRAFT"):
            action_po = next((po for po in po_list if po.get("status") == wanted), None)
            if action_po:
                break
        if action_po is None and po_list:
            action_po = po_list[0]

        all_dates_covered = not missing_dates and len(distribution_dates) > 0
        if all_dates_covered and statuses and statuses.issubset(done_statuses):
            reminder_status = "DONE"
        elif "FINALIZED" in statuses:
            reminder_status = "READY_TO_SEND"
        elif "DRAFT" in statuses:
            reminder_status = "DRAFT_NEEDS_FINAL"
        elif group["po_date"] == target_date:
            reminder_status = "DUE_TODAY"
        else:
            reminder_status = "UPCOMING"

        items.append(
            {
                **group,
                "distribution_date": distribution_dates[0] if distribution_dates else None,
                "distribution_dates": distribution_dates,
                "coverage_dates": distribution_dates,
                "cooking_date": cooking_dates[0] if cooking_dates else None,
                "cooking_dates": cooking_dates,
                "planned_distribution_count": len(distribution_dates),
                "covered_distribution_count": len(distribution_dates) - len(missing_dates),
                "missing_distribution_dates": missing_dates,
                "existing_po_count": len(po_list),
                "purchase_order_id": action_po.get("id") if action_po else None,
                "po_code": action_po.get("po_code") if action_po else None,
                "po_created_at": action_po.get("created_at") if action_po else None,
                "po_finalized_at": action_po.get("finalized_at") if action_po else None,
                "po_sent_at": action_po.get("sent_at") if action_po else None,
                "po_status": action_po.get("status") if action_po else None,
                "reminder_status": reminder_status,
            }
        )

    items.sort(key=lambda item: (item["po_date"], item["vendor_name"]))
    actionable = {"DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    return {
        "date": target_date,
        "horizonThrough": tomorrow,
        "site": normalized_site or None,
        "dueCount": sum(
            1 for item in items
            if item["po_date"] == target_date and item["reminder_status"] in actionable
        ),
        "tomorrowCount": sum(
            1 for item in items
            if item["po_date"] == tomorrow and item["reminder_status"] in actionable | {"UPCOMING"}
        ),
        "missingLeadTimeCount": missing_lead_time_count,
        "items": items,
    }
