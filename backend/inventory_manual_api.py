from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.inventory_api import normalize_location
from backend.stock_opname_parser import canonical_unit

# This router is included into backend.operational_api.router, which already owns
# the /v1 prefix. Keeping another /v1 here creates /v1/v1/inventory/manual-adjustment
# while the frontend correctly calls /v1/inventory/manual-adjustment.
router = APIRouter(tags=["inventory-manual"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def build_adjustment_movements(
    location: str,
    previous_unit: str,
    unit: str,
    before: float,
    target: float,
    delta: float,
    unit_changed: bool,
) -> list[dict[str, Any]]:
    """Describe auditable stock movements without mixing quantities across units."""
    if unit_changed:
        movements = []
        if before > 0:
            movements.append({
                "key_suffix": ":OUT_OLD_UNIT", "qty": before, "unit": previous_unit,
                "from_location": location, "to_location": "MANUAL_ADJUSTMENT",
                "balance_before": before, "target_balance": 0,
            })
        if target > 0:
            movements.append({
                "key_suffix": ":IN_NEW_UNIT", "qty": target, "unit": unit,
                "from_location": "MANUAL_ADJUSTMENT", "to_location": location,
                "balance_before": 0, "target_balance": target,
            })
        return movements
    if abs(delta) <= 0.00005:
        return []
    return [{
        "key_suffix": "", "qty": abs(delta), "unit": unit,
        "from_location": "MANUAL_ADJUSTMENT" if delta > 0 else location,
        "to_location": location if delta > 0 else "MANUAL_ADJUSTMENT",
        "balance_before": before, "target_balance": target,
    }]


class ManualStockAdjustmentIn(BaseModel):
    location: Literal["KOPERASI", "MAJA", "CEMPLANG"]
    item_name: str = Field(min_length=1)
    inventory_item_code: str | None = None
    unit: str | None = None
    previous_unit: str | None = None
    current_balance: float = 0
    target_balance: float = Field(ge=0)
    reason: str | None = None
    actor: str = "operator"
    occurred_at: datetime | None = None
    commit: bool = False


@router.post("/inventory/manual-adjustment")
def manual_stock_adjustment(payload: ManualStockAdjustmentIn) -> dict[str, Any]:
    """Set one visible stock balance by writing an auditable adjustment movement.

    This does not rewrite or delete SO evidence. With the same unit it inserts
    only the delta. When the operator changes units, it records the old balance
    out and the recounted balance in the new unit as auditable movements.
    """
    require_db()
    location = normalize_location(payload.location)
    item_name = payload.item_name.strip()
    unit = canonical_unit(payload.unit)
    previous_unit = canonical_unit(payload.previous_unit if payload.previous_unit is not None else payload.unit)
    unit_changed = previous_unit != unit
    before = round(float(payload.current_balance or 0), 4)
    target = round(float(payload.target_balance or 0), 4)
    delta = round(target - before, 4)
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    if unit_changed and not unit:
        raise HTTPException(422, "Satuan baru wajib diisi.")
    adjustment_type = "SET_BALANCE_WITH_UNIT_CHANGE" if unit_changed else "INCREASE" if delta > 0 else "DECREASE" if delta < 0 else "NO_CHANGE"
    result: dict[str, Any] = {
        "committed": False,
        "canCommit": unit_changed or abs(delta) > 0.00005,
        "location": location,
        "itemName": item_name,
        "inventoryItemCode": payload.inventory_item_code,
        "unit": unit,
        "previousUnit": previous_unit,
        "unitChanged": unit_changed,
        "balanceBefore": before,
        "targetBalance": target,
        "adjustmentQty": None if unit_changed else abs(delta),
        "adjustmentDelta": None if unit_changed else delta,
        "adjustmentType": adjustment_type,
        "reason": payload.reason,
    }
    if not unit_changed and abs(delta) <= 0.00005:
        result.update({"noChange": True})
        return result
    if unit_changed and before == 0 and target == 0:
        result.update({"noChange": True})
        return result
    if not payload.commit:
        return result

    canonical = {
        "location": location,
        "item_name": item_name,
        "inventory_item_code": payload.inventory_item_code,
        "unit": unit,
        "previous_unit": previous_unit,
        "before": before,
        "target": target,
        "delta": None if unit_changed else delta,
        "reason": payload.reason,
        "actor": payload.actor,
        "occurred_at": occurred_at.isoformat(),
    }
    source_key = "manual-stock-edit:" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    movements = build_adjustment_movements(location, previous_unit, unit, before, target, delta, unit_changed)

    with connection() as conn:
        with conn.cursor() as cur:
            movement_ids = []
            duplicates = 0
            for movement in movements:
                movement_source_key = source_key + movement["key_suffix"]
                cur.execute("select id from inventory_movements where source_key=%s", (movement_source_key,))
                duplicate = cur.fetchone()
                if duplicate:
                    movement_ids.append(duplicate["id"])
                    duplicates += 1
                    continue
                notes = json.dumps({
                    "reason": payload.reason or "Koreksi manual stok gudang",
                    "actor": payload.actor,
                    "balance_before": movement["balance_before"],
                    "target_balance": movement["target_balance"],
                    "delta": None if unit_changed else delta,
                    "unit_change": unit_changed,
                    "previous_unit": previous_unit,
                    "new_unit": unit,
                }, ensure_ascii=False)
                cur.execute(
                    """insert into inventory_movements(
                         movement_type,item_code,item_name,qty,unit,from_location,to_location,
                         occurred_at,source_type,source_key,source_ref,notes
                       ) values ('MANUAL_ADJUSTMENT',%s,%s,%s,%s,%s,%s,%s,
                                 'MANUAL_STOCK_EDIT',%s,%s,%s)
                       returning id""",
                    (
                        (payload.inventory_item_code or None), item_name, movement["qty"], movement["unit"],
                        movement["from_location"], movement["to_location"], occurred_at,
                        movement_source_key, f"manual-stock-edit:{location}", notes,
                    ),
                )
                movement_ids.append(cur.fetchone()["id"])
            conn.commit()
    result.update({
        "committed": True,
        "duplicate": duplicates == len(movements),
        "movementId": movement_ids[-1] if movement_ids else None,
        "movementIds": movement_ids,
        "sourceKey": source_key,
        "balanceAfter": target,
    })
    return result
