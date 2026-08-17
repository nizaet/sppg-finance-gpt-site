from __future__ import annotations

import hashlib
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


@router.post("/po-reminders/stock-confirmation")
def confirm_po_shortage_stock(payload: ShortageStockConfirmIn) -> dict[str, Any]:
    """Set checked kitchen stock through auditable inventory movements.

    The operator supplies the physical quantity currently seen in the kitchen.
    We compare it with the current *actual* ledger balance (not projected stock)
    and post only the delta. The latest physical SO remains untouched.
    """
    require_db()
    site = normalize_site(payload.site)
    jakarta = ZoneInfo("Asia/Jakarta")
    target_for_balance = datetime.now(jakarta).date() + timedelta(days=1)

    # Read current actual balance before opening the write transaction. Using
    # tomorrow as forDate includes all movements from today in actual_balance,
    # while planned depletion remains separate and is deliberately ignored here.
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
    unchanged = 0
    duplicates = 0
    with connection() as conn:
        with conn.cursor() as cur:
            for item in prepared:
                delta = float(item["delta"])
                if abs(delta) < 0.0001:
                    item["movement_status"] = "UNCHANGED"
                    unchanged += 1
                    continue

                cur.execute("select id from inventory_movements where source_key=%s", (item["source_key"],))
                existing = cur.fetchone()
                if existing:
                    item["movement_status"] = "DUPLICATE_IGNORED"
                    item["movement_id"] = existing["id"]
                    duplicates += 1
                    continue

                from_location, to_location = _correction_direction(site, delta)
                note_parts = [
                    f"Koreksi stok dari cek kekurangan PO {payload.reminder_key}",
                    f"stok_aktual_sebelum={item['current_actual_qty']}",
                    f"stok_fisik_dikonfirmasi={item['target_actual_qty']}",
                ]
                if payload.note:
                    note_parts.append(payload.note.strip())
                cur.execute(
                    """
                    insert into inventory_movements(
                      movement_type,item_code,item_name,qty,unit,from_location,to_location,
                      occurred_at,source_type,source_key,source_ref,notes
                    ) values (
                      'MANUAL_STOCK_CORRECTION',%s,%s,%s,%s,%s,%s,now(),
                      'PO_REMINDER_STOCK_CHECK',%s,%s,%s
                    ) returning id
                    """,
                    (
                        item["item_code"], item["item_name"], abs(delta), item["unit"],
                        from_location, to_location, item["source_key"], payload.reminder_key,
                        " | ".join(note_parts),
                    ),
                )
                item["movement_id"] = cur.fetchone()["id"]
                item["movement_status"] = "INSERTED"
                item["from_location"] = from_location
                item["to_location"] = to_location
                inserted += 1
        conn.commit()

    return {
        "site": site,
        "reminderKey": payload.reminder_key,
        "updated": inserted > 0,
        "inserted": inserted,
        "unchanged": unchanged,
        "duplicates": duplicates,
        "items": prepared,
        "message": (
            "Stok fisik dapur dicatat sebagai koreksi gudang. Reminder harus dihitung ulang dari stok terbaru."
            if inserted
            else "Stok yang dikonfirmasi sudah sama dengan saldo aktual; tidak ada movement baru."
        ),
    }
