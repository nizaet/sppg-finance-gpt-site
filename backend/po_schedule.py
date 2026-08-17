"""Shared, read-only scheduling helpers for saved purchase orders.

The source of truth for a PO's coverage remains ``purchase_order_coverage``.
This module only derives the earliest safe date to send the PO from the
effective vendor lead-time rules; it never changes a PO or a vendor rule.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from backend.item_taxonomy import item_family
from backend.po_reminder_v2_api import _norm, _rule_for_item


_ITEM_RULE_CATEGORY = {
    "EGG": "TELUR",
    "TEMPE": "TEMPE",
    "TOFU": "TAHU",
    "DRY_GOODS": "BAHAN_KERING",
    "CHICKEN": "AYAM",
    "FISH": "IKAN",
    "RICE": "BERAS",
    "GAS": "GAS",
    "PRODUCE": "SAYUR_BUAH",
}


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


def _dedicated_cemplang_tempe_rule(rules: list[dict[str, Any]], cook: date) -> dict[str, Any] | None:
    candidates = []
    for rule in rules:
        category = _norm(rule.get("category_code"))
        if "TEMPE" not in category or "TAHU" in category:
            continue
        if rule.get("effective_from") and rule["effective_from"] > cook:
            continue
        if rule.get("effective_to") and rule["effective_to"] < cook:
            continue
        candidates.append(rule)
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            str(row.get("site_code") or "").upper() == "CEMPLANG",
            _norm(row.get("category_code")) == "TEMPE",
            row.get("effective_from") or date.min,
            int(row.get("id") or 0),
        ),
        reverse=True,
    )
    return candidates[0]


def _item_rule(rules: list[dict[str, Any]], vendor: str, site: str, item_name: str, cook: date) -> dict[str, Any] | None:
    family = item_family(item_name)
    if vendor == "KOPERASI" and site == "CEMPLANG" and family == "TEMPE":
        return _dedicated_cemplang_tempe_rule(rules, cook)

    # Use the domain category name as a scoring hint.  This makes a dedicated
    # TELUR rule outrank legacy combined rules such as TELUR_TAHU_TEMPE, while
    # preserving family matching as a fallback for older data.
    category_hint = _ITEM_RULE_CATEGORY.get(family, family)
    return _rule_for_item(rules, vendor, site, category_hint, item_name, cook)


def _fallback_vendor_schedule(cur: Any, po: dict[str, Any], cooking_dates: list[date]) -> tuple[int | None, date | None]:
    earliest_cooking = cooking_dates[0] if cooking_dates else None
    if earliest_cooking is None:
        return None, None
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
    lead = int(value) if value is not None else None
    return lead, earliest_cooking - timedelta(days=lead) if lead is not None else None


def resolve_purchase_order_schedule(cur: Any, po: dict[str, Any]) -> dict[str, Any]:
    """Return the earliest item-specific safe date to send one saved PO.

    Important for KOPERASI: Telur, Tempe and dry goods may have different lead
    times even when vendor and distribution date are identical.  Therefore a
    split Telur PO must not inherit Tempe's longer lead or generic vendor lead.
    For a genuinely mixed PO, each item/date is evaluated and the earliest
    required order date wins.
    """
    cur.execute(
        """select id,distribution_date,cooking_date
           from purchase_order_coverage
           where purchase_order_id=%s
           order by distribution_date""",
        (po["id"],),
    )
    coverage = [dict(row) for row in cur.fetchall()]
    if not coverage:
        distribution = as_date(po.get("distribution_date"))
        coverage = [{
            "id": None,
            "distribution_date": distribution,
            "cooking_date": as_date(po.get("cooking_at")) or (distribution - timedelta(days=1) if distribution else None),
        }]

    distribution_dates = sorted({
        value for value in (as_date(row.get("distribution_date")) for row in coverage) if value is not None
    })
    cooking_dates = sorted({
        value
        for row in coverage
        for value in [as_date(row.get("cooking_date")) or (as_date(row.get("distribution_date")) - timedelta(days=1) if as_date(row.get("distribution_date")) else None)]
        if value is not None
    })
    earliest_cooking = cooking_dates[0] if cooking_dates else None

    vendor = str(po.get("vendor_code") or "").upper().strip()
    site = str(po.get("site") or "").upper().strip()
    if cooking_dates:
        cur.execute(
            """
            select vr.*
            from vendor_rules vr
            where upper(vr.vendor_code)=upper(%s)
              and (vr.site_code is null or upper(vr.site_code)=upper(%s))
              and vr.effective_from <= %s
              and (vr.effective_to is null or vr.effective_to >= %s)
            """,
            (vendor, site, cooking_dates[-1], cooking_dates[0]),
        )
        rules = [dict(row) for row in cur.fetchall()]
    else:
        rules = []

    direct_items: list[dict[str, Any]] | None = None
    lead_values: list[int] = []
    order_dates: list[date] = []
    unresolved_item_rule = False
    item_schedule_rows: list[dict[str, Any]] = []

    for row in coverage:
        distribution = as_date(row.get("distribution_date"))
        cook = as_date(row.get("cooking_date")) or (distribution - timedelta(days=1) if distribution else None)
        if cook is None:
            continue
        if row.get("id") is not None:
            cur.execute(
                """
                select item_name,po_qty,unit
                from purchase_order_coverage_items
                where purchase_order_coverage_id=%s and coalesce(po_qty,0)>0
                order by id
                """,
                (row["id"],),
            )
            items = [dict(item) for item in cur.fetchall()]
        else:
            items = []
        if not items:
            if direct_items is None:
                cur.execute(
                    """
                    select item_name,po_qty,unit
                    from purchase_order_items
                    where purchase_order_id=%s and coalesce(po_qty,0)>0
                    order by id
                    """,
                    (po["id"],),
                )
                direct_items = [dict(item) for item in cur.fetchall()]
            items = direct_items

        for item in items or []:
            rule = _item_rule(rules, vendor, site, str(item.get("item_name") or ""), cook)
            lead_raw = rule.get("lead_time_days_before_cooking") if rule else None
            if lead_raw is None:
                unresolved_item_rule = True
                continue
            lead = int(lead_raw)
            order_date = cook - timedelta(days=lead)
            lead_values.append(lead)
            order_dates.append(order_date)
            item_schedule_rows.append({
                "item_name": item.get("item_name"),
                "distribution_date": distribution,
                "cooking_date": cook,
                "lead_time_days_before_cooking": lead,
                "scheduled_order_date": order_date,
                "rule_category_code": rule.get("category_code") if rule else None,
            })

    # If every saved item can be resolved, item-specific scheduling is the source
    # of truth. Otherwise keep the old conservative vendor-level fallback rather
    # than pretending an unknown item has a shorter lead.
    if order_dates and not unresolved_item_rule:
        lead_time_days = max(lead_values) if lead_values else None
        scheduled_order_date = min(order_dates)
        schedule_basis = "ITEM_SPECIFIC_VENDOR_RULES"
    else:
        lead_time_days, scheduled_order_date = _fallback_vendor_schedule(cur, po, cooking_dates)
        schedule_basis = "VENDOR_MAX_FALLBACK" if scheduled_order_date is not None else "LEAD_TIME_MISSING"

    return {
        "coverage_dates": distribution_dates,
        "cooking_dates": cooking_dates,
        "cooking_date": earliest_cooking,
        "lead_time_days_before_cooking": lead_time_days,
        "scheduled_order_date": scheduled_order_date,
        "schedule_basis": schedule_basis,
        "item_schedule": item_schedule_rows,
    }
