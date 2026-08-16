"""Shared, read-only scheduling helpers for saved purchase orders.

The source of truth for a PO's coverage remains ``purchase_order_coverage``.
This module only derives the earliest safe date to send the PO from the
effective vendor lead-time rules; it never changes a PO or a vendor rule.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def as_date(value: Any) -> date | None:
    """Normalize a PostgreSQL/FastAPI date value without guessing a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def resolve_purchase_order_schedule(cur: Any, po: dict[str, Any]) -> dict[str, Any]:
    """Return dates and lead time needed to send one saved PO safely.

    A multi-day PO is sent once, on the earliest required date.  When a PO
    has mixed categories for the same vendor, the longest applicable lead
    time is used so the order is never sent too late.
    """
    cur.execute(
        """select distribution_date,cooking_date
           from purchase_order_coverage
           where purchase_order_id=%s
           order by distribution_date""",
        (po["id"],),
    )
    coverage = cur.fetchall()
    if coverage:
        distribution_dates = [as_date(row.get("distribution_date")) for row in coverage]
        cooking_dates = [as_date(row.get("cooking_date")) for row in coverage]
    else:
        distribution_date = as_date(po.get("distribution_date"))
        distribution_dates = [distribution_date] if distribution_date else []
        cooking_dates = [as_date(po.get("cooking_at"))]

    distribution_dates = sorted({value for value in distribution_dates if value is not None})
    cooking_dates = sorted({value for value in cooking_dates if value is not None})

    # Older POs may not have an explicit cooking date.  The existing planning
    # convention treats cooking as the day before distribution, so use that
    # documented fallback only for the schedule display.
    if not cooking_dates and distribution_dates:
        cooking_dates = [distribution_dates[0] - timedelta(days=1)]

    earliest_cooking = cooking_dates[0] if cooking_dates else None
    lead_time_days: int | None = None
    if earliest_cooking is not None:
        cur.execute(
            """select max(vr.lead_time_days_before_cooking) as lead_time_days
               from vendor_rules vr
               where upper(vr.vendor_code)=upper(%s)
                 and (vr.site_code is null or upper(vr.site_code)=upper(%s))
                 and vr.effective_from <= %s
                 and (vr.effective_to is null or vr.effective_to >= %s)""",
            (po.get("vendor_code"), po.get("site"), earliest_cooking, earliest_cooking),
        )
        rule = cur.fetchone() or {}
        value = rule.get("lead_time_days")
        lead_time_days = int(value) if value is not None else None

    scheduled_order_date = (
        earliest_cooking - timedelta(days=lead_time_days)
        if earliest_cooking is not None and lead_time_days is not None
        else None
    )
    return {
        "coverage_dates": distribution_dates,
        "cooking_dates": cooking_dates,
        "cooking_date": earliest_cooking,
        "lead_time_days_before_cooking": lead_time_days,
        "scheduled_order_date": scheduled_order_date,
    }
