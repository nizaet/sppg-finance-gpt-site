from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection
from backend.inventory_projection_v2_api import inventory_balances_v2
from backend.item_taxonomy import stock_type
from backend.operational_api import normalize_site, require_db
from backend.po_reminder_v3_api import po_reminders_v3
from backend.stock_opname_parser import canonical_unit

router = APIRouter(tags=["po-shortage-stock"])
EPSILON = 0.0001


class ShortageStockItemIn(BaseModel):
    item_name: str = Field(min_length=1, max_length=240)
    unit: str = Field(min_length=1, max_length=40)
    actual_stock_qty: float = Field(ge=0)


class ShortageStockConfirmIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    reminder_key: str = Field(min_length=8, max_length=100)
    items: list[ShortageStockItemIn] = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=500)


def _actual_balance_lookup(balance_items: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in balance_items:
        code = str(item.get("stock_type_code") or stock_type(item.get("item_name"))["code"]).upper().strip()
        unit = canonical_unit(item.get("unit")) or ""
        key = (code, unit)
        current = result.get(key)
        # balances-v2 is already grouped by type + unit. Keep the row with the
        # strongest explicit inventory identity if an unexpected duplicate exists.
        if current is None or (not current.get("inventory_item_code") and item.get("inventory_item_code")):
            result[key] = item
    return result


def _correction_direction(site: str, delta: float) -> tuple[str, str]:
    if delta > 0:
        return "MANUAL_CORRECTION", site
    return site, "MANUAL_CORRECTION"


def _source_key(reminder_key: str, type_code: str, unit: str, current_qty: float, target_qty: float) -> str:
    raw = f"{reminder_key}|{type_code}|{unit}|{current_qty:.4f}|{target_qty:.4f}"
    return "po-reminder-stock:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _detail_stock_key(detail: dict[str, Any]) -> tuple[str, str]:
    names = [str(value or "").strip() for value in (detail.get("item_names") or []) if str(value or "").strip()]
    type_code = str(detail.get("stock_type_code") or "").upper().strip()
    if not type_code and names:
        type_code = stock_type(names[0])["code"]
    return type_code, canonical_unit(detail.get("unit")) or ""


def _fresh_requirement_lookup(reminder: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Aggregate the *current* reminder shortage after exact PO coverage.

    ``remaining_po_qty`` is produced by the authoritative reminder engine only
    after matching saved PO rows by site, distribution date, item type and unit.
    Stock confirmation must use this live value instead of trusting the stale row
    that happened to be visible when the operator clicked the button.
    """
    result: dict[tuple[str, str], dict[str, Any]] = {}
    parent_po_codes = [
        *[str(value) for value in (reminder.get("partial_po_codes") or []) if value],
        *([str(reminder.get("po_code"))] if reminder.get("po_code") else []),
    ]
    for detail in reminder.get("requirement_details") or []:
        key = _detail_stock_key(detail)
        if not key[0] or not key[1]:
            continue
        row = result.setdefault(key, {
            "recommended_po_qty": 0.0,
            "covered_po_qty": 0.0,
            "remaining_po_qty": 0.0,
            "distribution_dates": [],
            "po_codes": [],
        })
        row["recommended_po_qty"] = round(
            float(row["recommended_po_qty"]) + float(detail.get("recommended_po_qty") or 0), 4
        )
        row["covered_po_qty"] = round(
            float(row["covered_po_qty"]) + float(detail.get("covered_po_qty") or 0), 4
        )
        row["remaining_po_qty"] = round(
            float(row["remaining_po_qty"]) + float(detail.get("remaining_po_qty") or 0), 4
        )
        distribution = detail.get("distribution_date")
        if distribution and str(distribution) not in row["distribution_dates"]:
            row["distribution_dates"].append(str(distribution))
        for code in [*parent_po_codes, detail.get("completed_po_code")]:
            code_text = str(code or "").strip()
            if code_text and code_text not in row["po_codes"]:
                row["po_codes"].append(code_text)
    return result


def _find_live_reminder(site: str, reminder_key: str, target_date) -> dict[str, Any] | None:
    """Force a fresh PO/reminder calculation before any stock write."""
    payload = po_reminders_v3(
        site=site,
        as_of=target_date,
        horizon_days=2,
        refresh=True,
    )
    for item in payload.get("items") or []:
        if str(item.get("reminder_key") or "") == reminder_key:
            return item
    return None


def _clear_legacy_stock_confirmation_override(cur: Any, reminder_key: str) -> None:
    """Remove only the old auto-close override created by stock confirmation.

    Stock confirmation is a physical recount, not a manual instruction to force a
    reminder DONE. After the recount, the normal reminder engine must recompute
    the shortage from physical stock + running planning + saved PO coverage.
    Explicit MANUAL_PO/CHECKED/SUFFICIENT overrides created by the operator are
    deliberately left untouched.
    """
    cur.execute(
        """
        update po_reminder_overrides
        set active=false, updated_at=now()
        where reminder_key=%s
          and active=true
          and coalesce(metadata->>'source','')='PO_REMINDER_STOCK_CONFIRMATION'
        """,
        (reminder_key,),
    )


def _audit_notes(payload: ShortageStockConfirmIn, item: dict[str, Any]) -> str:
    """Structured recount metadata understood by the inventory projection."""
    return json.dumps(
        {
            "source": "PO_REMINDER_STOCK_CONFIRMATION",
            "reminder_key": payload.reminder_key,
            "target_balance": item["target_actual_qty"],
            "previous_balance": item["current_actual_qty"],
            "stock_type_code": item["stock_type_code"],
            "fresh_recommended_po_qty": item.get("fresh_recommended_po_qty"),
            "fresh_covered_po_qty": item.get("fresh_covered_po_qty"),
            "fresh_remaining_po_qty": item.get("fresh_remaining_po_qty"),
            "fresh_po_codes": item.get("fresh_po_codes") or [],
            "operator_note": payload.note or None,
        },
        ensure_ascii=False,
        default=str,
    )


@router.post("/po-reminders/stock-confirmation")
def confirm_po_shortage_stock(payload: ShortageStockConfirmIn) -> dict[str, Any]:
    """Confirm shortage stock only after rechecking existing PO coverage.

    The action is deliberately two-layered:
    1. Force-refresh the reminder engine so exact saved PO coverage is checked first.
    2. Only items that still have an uncovered PO quantity may write a physical
       stock correction. If the requirement is already covered by a PO, warehouse
       stock is left untouched.

    This prevents the old failure mode where clicking "Konfirmasi stok gudang"
    immediately changed warehouse stock even though the shortage had already been
    ordered. MAJA and CEMPLANG use the same rule.
    """
    require_db()
    site = normalize_site(payload.site)
    jakarta = ZoneInfo("Asia/Jakarta")
    today_jakarta = datetime.now(jakarta).date()

    # Re-read PO + reminder state immediately before any mutation. If the reminder
    # disappeared, it has already been resolved/replaced; safest behavior is no-op.
    live_reminder = _find_live_reminder(site, payload.reminder_key, today_jakarta)
    if live_reminder is None:
        return {
            "site": site,
            "reminderKey": payload.reminder_key,
            "updated": False,
            "stockChanged": False,
            "alreadyCovered": True,
            "inserted": 0,
            "changed": 0,
            "unchanged": 0,
            "duplicates": 0,
            "items": [],
            "message": (
                "Stok TIDAK diubah. Setelah cek ulang PO terbaru, reminder ini sudah tidak aktif/"
                "sudah tercakup. Refresh pengingat untuk melihat PO yang menutup kebutuhan."
            ),
        }

    fresh_requirements = _fresh_requirement_lookup(live_reminder)
    target_for_balance = today_jakarta + timedelta(days=1)
    balances = inventory_balances_v2(site=site, search="", limit=1000, for_date=target_for_balance)
    lookup = _actual_balance_lookup(balances.get("items") or [])

    prepared: list[dict[str, Any]] = []
    skipped_covered: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for line in payload.items:
        typed = stock_type(line.item_name)
        unit = canonical_unit(line.unit) or ""
        if not unit:
            raise HTTPException(400, f"Satuan {line.item_name} wajib diisi")
        key = (typed["code"], unit)
        fresh = fresh_requirements.get(key)

        # A click can be based on a stale browser row. The live reminder is the
        # authority. Never write stock for a type/unit that is no longer short.
        if fresh is None or float(fresh.get("remaining_po_qty") or 0) <= EPSILON:
            skipped_covered.append({
                "item_name": typed["label"] or line.item_name.strip(),
                "raw_item_name": line.item_name.strip(),
                "stock_type_code": typed["code"],
                "unit": unit,
                "confirmed_physical_qty": round(float(line.actual_stock_qty), 4),
                "fresh_recommended_po_qty": round(float((fresh or {}).get("recommended_po_qty") or 0), 4),
                "fresh_covered_po_qty": round(float((fresh or {}).get("covered_po_qty") or 0), 4),
                "fresh_remaining_po_qty": round(float((fresh or {}).get("remaining_po_qty") or 0), 4),
                "fresh_po_codes": list((fresh or {}).get("po_codes") or []),
                "movement_status": "SKIPPED_ALREADY_COVERED_BY_PO",
            })
            continue

        # One physical count per ingredient type/unit. A grouped reminder can have
        # several dates for the same item; writing the same recount twice would
        # create duplicate stock. The live remaining qty is already aggregated.
        if key in seen_keys:
            continue
        seen_keys.add(key)

        current_row = lookup.get(key) or {}
        current_qty = round(float(current_row.get("actual_balance") or 0), 4)
        target_qty = round(float(line.actual_stock_qty), 4)
        delta = round(target_qty - current_qty, 4)
        remaining_before_stock = round(float(fresh.get("remaining_po_qty") or 0), 4)
        prepared.append({
            "item_name": typed["label"] or line.item_name.strip(),
            "raw_item_name": line.item_name.strip(),
            "item_code": current_row.get("inventory_item_code"),
            "stock_type_code": typed["code"],
            "unit": unit,
            "current_actual_qty": current_qty,
            "target_actual_qty": target_qty,
            "delta": delta,
            "fresh_recommended_po_qty": round(float(fresh.get("recommended_po_qty") or 0), 4),
            "fresh_covered_po_qty": round(float(fresh.get("covered_po_qty") or 0), 4),
            "fresh_remaining_po_qty": remaining_before_stock,
            "fresh_po_codes": list(fresh.get("po_codes") or []),
            "estimated_remaining_after_physical": max(0.0, round(remaining_before_stock - target_qty, 4)),
            "estimated_surplus_after_current_need": max(0.0, round(target_qty - remaining_before_stock, 4)),
            "source_key": _source_key(payload.reminder_key, typed["code"], unit, current_qty, target_qty),
        })

    # Most important guard: when fresh PO coverage already closes every requested
    # item, confirmation becomes read-only and cannot alter warehouse balances.
    if not prepared:
        po_codes = sorted({code for item in skipped_covered for code in item.get("fresh_po_codes") or []})
        return {
            "site": site,
            "reminderKey": payload.reminder_key,
            "updated": False,
            "stockChanged": False,
            "alreadyCovered": True,
            "inserted": 0,
            "changed": 0,
            "unchanged": 0,
            "duplicates": 0,
            "poCodes": po_codes,
            "items": skipped_covered,
            "message": (
                "Stok TIDAK diubah. Kekurangan ini sudah tercakup PO yang sedang berjalan"
                + (f": {', '.join(po_codes)}." if po_codes else ".")
                + " Refresh pengingat sebelum membuat PO tambahan."
            ),
        }

    inserted = 0
    changed = 0
    unchanged = 0
    duplicates = 0
    legacy_overrides_cleared = 0
    with connection() as conn:
        with conn.cursor() as cur:
            _clear_legacy_stock_confirmation_override(cur, payload.reminder_key)
            legacy_overrides_cleared = max(0, int(getattr(cur, "rowcount", 0) or 0))

            for item in prepared:
                delta = float(item["delta"])

                cur.execute("select id from inventory_movements where source_key=%s", (item["source_key"],))
                existing = cur.fetchone()
                if existing:
                    item["movement_status"] = "DUPLICATE_IGNORED"
                    item["movement_id"] = existing["id"]
                    duplicates += 1
                    continue

                # Even an unchanged physical count establishes a new physical-check
                # boundary for this exact item. It has zero quantity effect.
                if abs(delta) < EPSILON:
                    movement_qty = 0.0
                    from_location = site
                    to_location = site
                    unchanged += 1
                else:
                    movement_qty = abs(delta)
                    from_location, to_location = _correction_direction(site, delta)
                    changed += 1

                cur.execute(
                    """
                    insert into inventory_movements(
                      movement_type,item_code,item_name,qty,unit,from_location,to_location,
                      occurred_at,source_type,source_key,source_ref,notes
                    ) values (
                      'MANUAL_STOCK_CORRECTION',%s,%s,%s,%s,%s,%s,now(),
                      'MANUAL_STOCK_EDIT',%s,%s,%s
                    ) returning id
                    """,
                    (
                        item["item_code"], item["item_name"], movement_qty, item["unit"],
                        from_location, to_location, item["source_key"],
                        f"PO_REMINDER_STOCK_CHECK:{payload.reminder_key}",
                        _audit_notes(payload, item),
                    ),
                )
                item["movement_id"] = cur.fetchone()["id"]
                item["movement_status"] = "PHYSICAL_CHECK_RECORDED" if abs(delta) < EPSILON else "INSERTED"
                item["from_location"] = from_location
                item["to_location"] = to_location
                inserted += 1

        conn.commit()

    # Recalculate once more after the stock write so the response tells the UI the
    # resulting shortage, not merely the pre-write estimate.
    post_reminder = _find_live_reminder(site, payload.reminder_key, today_jakarta)
    post_lookup = _fresh_requirement_lookup(post_reminder or {})
    for item in prepared:
        post = post_lookup.get((item["stock_type_code"], item["unit"])) or {}
        item["post_remaining_po_qty"] = round(float(post.get("remaining_po_qty") or 0), 4)

    all_items = [*prepared, *skipped_covered]
    return {
        "site": site,
        "reminderKey": payload.reminder_key,
        "updated": inserted > 0,
        "stockChanged": changed > 0,
        "alreadyCovered": False,
        "inserted": inserted,
        "changed": changed,
        "unchanged": unchanged,
        "duplicates": duplicates,
        "legacyOverridesCleared": legacy_overrides_cleared,
        "overrideSaved": False,
        "reminderRecalculation": "FRESH_PO_COVERAGE_THEN_PHYSICAL_STOCK",
        "items": all_items,
        "message": (
            "PO dicek ulang lebih dulu. Stok fisik hanya dikoreksi untuk item yang masih benar-benar kurang setelah coverage PO terbaru; item yang sudah tercakup PO tidak mengubah gudang."
        ),
    }
