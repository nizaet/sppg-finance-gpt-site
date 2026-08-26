from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection, database_ready

router = APIRouter(tags=["vendor-rule-admin"])


class VendorLeadTimeUpdateIn(BaseModel):
    vendor_code: str = Field(min_length=1, max_length=100)
    site_code: str | None = None
    category_code: str | None = None
    lead_time_days_before_cooking: int = Field(ge=0, le=30)
    effective_from: date | None = None
    note: str = "Updated from Pusat Operasional"


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _clean_nullable(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _update_active_lead_time(
    vendor: str,
    site: str | None,
    category: str | None,
    effective_from: date,
    lead_time: int,
    note: str,
) -> dict[str, Any] | None:
    """Last-resort write for legacy rows that cannot be split into a revision.

    Some historical database rows predate the effective-dated editor and reject
    a close+insert revision.  Updating that one active row is safe: its vendor,
    site, category, payment settings and references stay unchanged.
    """
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with active_rule as (
                  select id
                  from vendor_rules
                  where vendor_code=%s
                    and site_code is not distinct from %s
                    and category_code is not distinct from %s
                    and effective_from <= %s
                    and (effective_to is null or effective_to >= %s)
                  order by effective_from desc, id desc
                  limit 1
                )
                update vendor_rules vr
                set lead_time_days_before_cooking=%s,
                    notes=concat_ws(' | ', nullif(vr.notes,''), %s)
                from active_rule
                where vr.id=active_rule.id
                returning vr.id,vr.effective_from
                """,
                (vendor, site, category, effective_from, effective_from, lead_time, note),
            )
            updated = cur.fetchone()
            conn.commit()
            return updated


@router.post("/reference/vendor-rules/lead-time")
def update_vendor_lead_time(payload: VendorLeadTimeUpdateIn) -> dict[str, Any]:
    """Create an effective-dated lead-time revision without rewriting history."""
    require_db()
    vendor = payload.vendor_code.upper().strip()
    site = _clean_nullable(payload.site_code.upper() if payload.site_code else None)
    category = _clean_nullable(payload.category_code.upper() if payload.category_code else None)
    effective_from = payload.effective_from or date.today()

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select code,name from entities where code=%s and active=true", (vendor,))
                if not cur.fetchone():
                    raise HTTPException(404, "vendor tidak ditemukan")

                # Lock the active revision.  Double-clicks or two operators editing
                # the same rule used to race between the close and insert queries,
                # causing PostgreSQL's unique rule to bubble up as a 500.
                cur.execute(
                    """
                    select * from vendor_rules
                    where vendor_code=%s
                      and site_code is not distinct from %s
                      and category_code is not distinct from %s
                      and effective_from <= %s
                      and (effective_to is null or effective_to >= %s)
                    order by effective_from desc, id desc
                    limit 1
                    for update
                    """,
                    (vendor, site, category, effective_from, effective_from),
                )
                current = cur.fetchone()
                if not current:
                    raise HTTPException(404, "rule vendor aktif untuk kombinasi site/kategori ini tidak ditemukan")

                current_lead = current.get("lead_time_days_before_cooking")
                if current_lead is not None and int(current_lead) == payload.lead_time_days_before_cooking:
                    return {
                        "changed": False,
                        "ruleId": current["id"],
                        "vendorCode": vendor,
                        "siteCode": site,
                        "categoryCode": category,
                        "leadTimeDaysBeforeCooking": payload.lead_time_days_before_cooking,
                        "effectiveFrom": current["effective_from"],
                    }

                if current["effective_from"] == effective_from:
                    cur.execute(
                        """update vendor_rules
                           set lead_time_days_before_cooking=%s,
                               notes=concat_ws(' | ', nullif(notes,''), %s)
                           where id=%s
                           returning id,effective_from""",
                        (payload.lead_time_days_before_cooking, payload.note, current["id"]),
                    )
                    updated = cur.fetchone()
                    conn.commit()
                    return {
                        "changed": True,
                        "mode": "same_day_update",
                        "ruleId": updated["id"],
                        "vendorCode": vendor,
                        "siteCode": site,
                        "categoryCode": category,
                        "leadTimeDaysBeforeCooking": payload.lead_time_days_before_cooking,
                        "effectiveFrom": updated["effective_from"],
                    }

                cur.execute("update vendor_rules set effective_to=%s where id=%s", (effective_from - timedelta(days=1), current["id"]))
                cur.execute(
                    """
                    insert into vendor_rules(
                      vendor_code,site_code,category_code,lead_time_days_before_cooking,
                      payment_term_code,payment_term_payload,internal_reimbursement,
                      intermediary_code,effective_from,effective_to,evidence_ref,notes
                    ) values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,null,%s,%s)
                    on conflict(vendor_code,site_code,category_code,effective_from)
                    do update set lead_time_days_before_cooking=excluded.lead_time_days_before_cooking,
                                  notes=concat_ws(' | ', nullif(vendor_rules.notes,''), excluded.notes),
                                  effective_to=null
                    returning id,effective_from
                    """,
                    (
                        vendor, site, category, payload.lead_time_days_before_cooking,
                        current.get("payment_term_code"), json.dumps(current.get("payment_term_payload") or {}),
                        bool(current.get("internal_reimbursement")), current.get("intermediary_code"),
                        effective_from, current.get("evidence_ref"), payload.note,
                    ),
                )
                created = cur.fetchone()
                conn.commit()
                return {
                    "changed": True,
                    "mode": "effective_dated_revision",
                    "ruleId": created["id"],
                    "vendorCode": vendor,
                    "siteCode": site,
                    "categoryCode": category,
                    "leadTimeDaysBeforeCooking": payload.lead_time_days_before_cooking,
                    "effectiveFrom": created["effective_from"],
                    "previousRuleId": current["id"],
                }
    except HTTPException:
        raise
    except psycopg.Error as exc:
        # A few legacy rows were created before the effective-dated editor. If
        # their close+insert revision fails, retain every field and update the
        # active rule itself rather than blocking the operational lead-time edit.
        try:
            updated = _update_active_lead_time(
                vendor, site, category, effective_from,
                payload.lead_time_days_before_cooking, payload.note,
            )
        except psycopg.Error as fallback_exc:
            raise HTTPException(409, "Lead time belum tersimpan. Refresh halaman lalu coba sekali lagi.") from fallback_exc
        if not updated:
            raise HTTPException(404, "rule vendor aktif untuk kombinasi site/kategori ini tidak ditemukan") from exc
        return {
            "changed": True,
            "mode": "active_rule_update",
            "ruleId": updated["id"],
            "vendorCode": vendor,
            "siteCode": site,
            "categoryCode": category,
            "leadTimeDaysBeforeCooking": payload.lead_time_days_before_cooking,
            "effectiveFrom": updated["effective_from"],
        }
