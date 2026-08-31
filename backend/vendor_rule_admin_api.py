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
    new_vendor_code: str | None = Field(default=None, min_length=1, max_length=100)
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


def _entity_exists(cur: Any, vendor: str) -> bool:
    cur.execute(
        "select code from entities where code=%s and active=true and entity_type in ('VENDOR','INTERNAL_ORG')",
        (vendor,),
    )
    return bool(cur.fetchone())


def _active_rule(
    cur: Any,
    vendor: str,
    site: str | None,
    category: str | None,
    effective_from: date,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    sql = """
        select * from vendor_rules
        where vendor_code=%s
          and site_code is not distinct from %s
          and category_code is not distinct from %s
          and effective_from <= %s
          and (effective_to is null or effective_to >= %s)
        order by effective_from desc, id desc
        limit 1
    """
    if for_update:
        sql += " for update"
    cur.execute(sql, (vendor, site, category, effective_from, effective_from))
    row = cur.fetchone()
    return dict(row) if row else None


def _close_rule(cur: Any, rule: dict[str, Any], effective_from: date) -> None:
    if rule["effective_from"] < effective_from:
        cur.execute(
            "update vendor_rules set effective_to=%s where id=%s",
            (effective_from - timedelta(days=1), rule["id"]),
        )
    else:
        # A rule created today has no historical day to preserve. Removing it is
        # cleaner than creating an invalid effective_to < effective_from range.
        cur.execute("delete from vendor_rules where id=%s", (rule["id"],))


def _upsert_reassigned_rule(
    cur: Any,
    *,
    old_rule: dict[str, Any],
    target_vendor: str,
    site: str | None,
    category: str | None,
    effective_from: date,
    lead_time: int,
    note: str,
) -> dict[str, Any]:
    existing_target = _active_rule(cur, target_vendor, site, category, effective_from, for_update=True)

    # Close the old assignment first. For a same-day row this intentionally
    # deletes only today's not-yet-historical revision.
    _close_rule(cur, old_rule, effective_from)

    if existing_target and int(existing_target["id"]) != int(old_rule["id"]):
        if existing_target["effective_from"] == effective_from:
            cur.execute(
                """update vendor_rules
                   set lead_time_days_before_cooking=%s,effective_to=null,
                       notes=concat_ws(' | ',nullif(notes,''),%s)
                   where id=%s
                   returning id,effective_from""",
                (lead_time, note, existing_target["id"]),
            )
            return dict(cur.fetchone())
        _close_rule(cur, existing_target, effective_from)

    cur.execute(
        """
        insert into vendor_rules(
          vendor_code,site_code,category_code,lead_time_days_before_cooking,
          payment_term_code,payment_term_payload,internal_reimbursement,
          intermediary_code,effective_from,effective_to,evidence_ref,notes
        ) values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,null,%s,%s)
        on conflict(vendor_code,site_code,category_code,effective_from)
        do update set lead_time_days_before_cooking=excluded.lead_time_days_before_cooking,
                      payment_term_code=coalesce(vendor_rules.payment_term_code,excluded.payment_term_code),
                      payment_term_payload=case
                        when vendor_rules.payment_term_payload is null or vendor_rules.payment_term_payload='{}'::jsonb
                        then excluded.payment_term_payload else vendor_rules.payment_term_payload end,
                      internal_reimbursement=vendor_rules.internal_reimbursement or excluded.internal_reimbursement,
                      intermediary_code=coalesce(vendor_rules.intermediary_code,excluded.intermediary_code),
                      notes=concat_ws(' | ',nullif(vendor_rules.notes,''),excluded.notes),
                      effective_to=null
        returning id,effective_from
        """,
        (
            target_vendor, site, category, lead_time,
            old_rule.get("payment_term_code"), json.dumps(old_rule.get("payment_term_payload") or {}),
            bool(old_rule.get("internal_reimbursement")), old_rule.get("intermediary_code"),
            effective_from, old_rule.get("evidence_ref"), note,
        ),
    )
    return dict(cur.fetchone())


def _update_active_lead_time(
    vendor: str,
    site: str | None,
    category: str | None,
    effective_from: date,
    lead_time: int,
    note: str,
) -> dict[str, Any] | None:
    """Last-resort write for legacy rows that cannot be split into a revision."""
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
    """Edit vendor assignment and lead time while preserving effective history."""
    require_db()
    vendor = payload.vendor_code.upper().strip()
    target_vendor = (payload.new_vendor_code or vendor).upper().strip()
    site = _clean_nullable(payload.site_code.upper() if payload.site_code else None)
    category = _clean_nullable(payload.category_code.upper() if payload.category_code else None)
    effective_from = payload.effective_from or date.today()

    # Vendor reassignment is deliberately handled separately from the legacy
    # lead-time fallback. A failed reassignment must never silently edit the old
    # vendor and pretend the vendor change succeeded.
    if target_vendor != vendor:
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    if not _entity_exists(cur, vendor):
                        raise HTTPException(404, "vendor lama tidak ditemukan")
                    if not _entity_exists(cur, target_vendor):
                        raise HTTPException(404, "vendor baru tidak ditemukan")
                    current = _active_rule(cur, vendor, site, category, effective_from, for_update=True)
                    if not current:
                        raise HTTPException(404, "rule vendor aktif untuk kombinasi site/kategori ini tidak ditemukan")
                    created = _upsert_reassigned_rule(
                        cur,
                        old_rule=current,
                        target_vendor=target_vendor,
                        site=site,
                        category=category,
                        effective_from=effective_from,
                        lead_time=payload.lead_time_days_before_cooking,
                        note=f"{payload.note} | vendor {vendor} -> {target_vendor}",
                    )
                    conn.commit()
                    return {
                        "changed": True,
                        "vendorChanged": True,
                        "mode": "effective_dated_vendor_reassignment",
                        "ruleId": created["id"],
                        "vendorCode": target_vendor,
                        "previousVendorCode": vendor,
                        "siteCode": site,
                        "categoryCode": category,
                        "leadTimeDaysBeforeCooking": payload.lead_time_days_before_cooking,
                        "effectiveFrom": created["effective_from"],
                        "previousRuleId": current["id"],
                    }
        except HTTPException:
            raise
        except psycopg.Error as exc:
            raise HTTPException(409, "Vendor belum tersimpan. Refresh halaman lalu coba sekali lagi.") from exc

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                if not _entity_exists(cur, vendor):
                    raise HTTPException(404, "vendor tidak ditemukan")

                current = _active_rule(cur, vendor, site, category, effective_from, for_update=True)
                if not current:
                    raise HTTPException(404, "rule vendor aktif untuk kombinasi site/kategori ini tidak ditemukan")

                current_lead = current.get("lead_time_days_before_cooking")
                if current_lead is not None and int(current_lead) == payload.lead_time_days_before_cooking:
                    return {
                        "changed": False,
                        "vendorChanged": False,
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
                        "vendorChanged": False,
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
                    "vendorChanged": False,
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
            "vendorChanged": False,
            "mode": "active_rule_update",
            "ruleId": updated["id"],
            "vendorCode": vendor,
            "siteCode": site,
            "categoryCode": category,
            "leadTimeDaysBeforeCooking": payload.lead_time_days_before_cooking,
            "effectiveFrom": updated["effective_from"],
        }