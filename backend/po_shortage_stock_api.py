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
from backend.stock_opname_parser import canonical_unit

router = APIRouter(tags=["po-shortage-stock"])


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
    """Structured recount metadata understood by the inventory projection.

    `target_balance` intentionally makes this movement a new per-item physical
    stock anchor. Plans before this check are estimates that have already been
    absorbed by the human count; plans on/after the check remain available for
    the normal PO projection.
    """
    return json.dumps(
        {
            "source": "PO_REMINDER_STOCK_CONFIRMATION",
            "reminder_key": payload.reminder_key,
            "target_balance": item["target_actual_qty"],
            "previous_balance": item["current_actual_qty"],
            "stock_type_code": item["stock_type_code"],
            "operator_note": payload.note or None,
        },
        ensure_ascii=False,
        default=str,
    )


@router.post("/po-reminders/stock-confirmation")
def confirm_po_shortage_stock(payload: ShortageStockConfirmIn) -> dict[str, Any]:
    """Record a physical kitchen recount and let the PO reminder recalculate.

    The operator enters the total physical quantity currently seen in the selected
    kitchen. We post only the delta against the current actual ledger balance, but
    the confirmation itself becomes a fresh physical-stock anchor even when the
    delta is zero. The current/future cooking plan and any saved PO remain separate
    layers and are applied by the projection after this physical check.

    Therefore, if the operator confirms more stock than the running requirement,
    only the surplus remains available for later PO. If the stock is equal to the
    requirement, the projected surplus is zero. If it is lower, the reminder stays
    open for the remaining shortage. The same rule is used for MAJA and CEMPLANG.
    """
    require_db()
    site = normalize_site(payload.site)
    jakarta = ZoneInfo("Asia/Jakarta")
    target_for_balance = datetime.now(jakarta).date() + timedelta(days=1)

    # Tomorrow includes all movements posted today in actual_balance while the
    # running/future planning depletion stays separate for reminder recalculation.
    balances = inventory_balances_v2(site=site, search="", limit=1000, for_date=target_for_balance)
    lookup = _actual_balance_lookup(balances.get("items") or [])

    prepared: list[dict[str, Any]] = []
    for line in payload.items:
        typed = stock_type(line.item_name)
        unit = canonical_unit(line.unit) or ""
        if not unit:
            raise HTTPException(400, f"Satuan {line.item_name} wajib diisi")
        current_row = lookup.get((typed["code"], unit)) or {}
        current_qty = round(float(current_row.get("actual_balance") or 0), 4)
        target_qty = round(float(line.actual_stock_qty), 4)
        delta = round(target_qty - current_qty, 4)
        prepared.append({
            "item_name": typed["label"] or line.item_name.strip(),
            "raw_item_name": line.item_name.strip(),
            "item_code": current_row.get("inventory_item_code"),
            "stock_type_code": typed["code"],
            "unit": unit,
            "current_actual_qty": current_qty,
            "target_actual_qty": target_qty,
            "delta": delta,
            "source_key": _source_key(payload.reminder_key, typed["code"], unit, current_qty, target_qty),
        })

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

                # Even an unchanged physical count is meaningful: it establishes
                # that this exact item was physically checked now. A zero-qty
                # same-location audit movement has no quantity effect but gives
                # the projection a deterministic recount boundary.
                if abs(delta) < 0.0001:
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
                item["movement_status"] = "PHYSICAL_CHECK_RECORDED" if abs(delta) < 0.0001 else "INSERTED"
                item["from_location"] = from_location
                item["to_location"] = to_location
                inserted += 1

        conn.commit()

    return {
        "site": site,
        "reminderKey": payload.reminder_key,
        "updated": inserted > 0,
        "stockChanged": changed > 0,
        "inserted": inserted,
        "changed": changed,
        "unchanged": unchanged,
        "duplicates": duplicates,
        "legacyOverridesCleared": legacy_overrides_cleared,
        "overrideSaved": False,
        "reminderRecalculation": "PHYSICAL_STOCK_MINUS_RUNNING_PLAN_AND_PO_COVERAGE",
        "items": prepared,
        "message": (
            "Stok fisik dapur disimpan sebagai patokan terbaru. Reminder dihitung ulang dari stok, planning, dan PO berjalan: jika cukup akan selesai, jika masih kurang sisa kekurangan tetap terbuka; kelebihan tetap menjadi stok gudang."
        ),
    }
