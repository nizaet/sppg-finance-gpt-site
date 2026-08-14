from __future__ import annotations

from datetime import date, timedelta
from typing import Any

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


@router.post("/reference/vendor-rules/lead-time")
def update_vendor_lead_time(payload: VendorLeadTimeUpdateIn) -> dict[str, Any]:
    """Create an effective-dated lead-time revision without rewriting history.

    If the current rule starts on the same effective date, update that same row.
    Otherwise close the old rule one day before the new rule and clone the rest
    of the rule fields into a new row with the edited lead time.
    """
    require_db()
    vendor = payload.vendor_code.upper().strip()
    site = _clean_nullable(payload.site_code.upper() if payload.site_code else None)
    category = _clean_nullable(payload.category_code)
    effective_from = payload.effective_from or date.today()

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select code,name from entities where code=%s and active=true", (vendor,))
            vendor_row = cur.fetchone()
            if not vendor_row:
                raise HTTPException(404, "vendor tidak ditemukan")

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
                """,
                (vendor, site, category, effective_from, effective_from),
            )
            current = cur.fetchone()
            if not current:
                raise HTTPException(404, "rule vendor aktif untuk kombinasi site/kategori ini tidak ditemukan")

            if int(current.get("lead_time_days_before_cooking") or 0) == payload.lead_time_days_before_cooking:
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

            cur.execute(
                "update vendor_rules set effective_to=%s where id=%s",
                (effective_from - timedelta(days=1), current["id"]),
            )
            cur.execute(
                """
                insert into vendor_rules(
                  vendor_code,site_code,category_code,lead_time_days_before_cooking,
                  payment_term_code,payment_term_payload,internal_reimbursement,
                  intermediary_code,effective_from,effective_to,evidence_ref,notes
                ) values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,null,%s,%s)
                returning id,effective_from
                """,
                (
                    vendor,
                    site,
                    category,
                    payload.lead_time_days_before_cooking,
                    current.get("payment_term_code"),
                    __import__("json").dumps(current.get("payment_term_payload") or {}),
                    bool(current.get("internal_reimbursement")),
                    current.get("intermediary_code"),
                    effective_from,
                    current.get("evidence_ref"),
                    payload.note,
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
