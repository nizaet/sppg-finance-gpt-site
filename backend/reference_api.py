from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from backend.db import connection, database_ready
from backend.vendor_payables_api import router as vendor_payables_router
from backend.operational_search_api import router as operational_search_router
from backend.operational_history_api import router as operational_history_router
from backend.operations_action_schema_api import router as operations_action_schema_router
from backend.operations_action_schema_fix_api import router as operations_action_schema_fix_router

router = APIRouter(prefix="/v1", tags=["reference"])
router.include_router(vendor_payables_router)
router.include_router(operational_search_router)
router.include_router(operational_history_router)
router.include_router(operations_action_schema_router)
router.include_router(operations_action_schema_fix_router)


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
        "distributionDate": distribution_date,
        "cookingDate": cook,
        "site": site or None,
        "items": items,
    }
