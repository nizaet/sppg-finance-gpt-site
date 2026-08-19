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


class ManualStockAdjustmentIn(BaseModel):
    location: Literal["KOPERASI", "MAJA", "CEMPLANG"]
    item_name: str = Field(min_length=1)
    inventory_item_code: str | None = None
    unit: str | None = None
    current_balance: float = 0
    target_balance: float = Field(ge=0)
    reason: str | None = None
    actor: str = "operator"
    occurred_at: datetime | None = None
    commit: bool = False


@router.post("/inventory/manual-adjustment")
def manual_stock_adjustment(payload: ManualStockAdjustmentIn) -> dict[str, Any]:
    """Set one visible stock balance by writing an auditable adjustment movement.

    This does not rewrite or delete SO evidence. It inserts only the delta needed
    to make the currently displayed stock equal the operator's corrected value.
    """
    require_db()
    location = normalize_location(payload.location)
    item_name = payload.item_name.strip()
    unit = canonical_unit(payload.unit)
    before = round(float(payload.current_balance or 0), 4)
    target = round(float(payload.target_balance or 0), 4)
    delta = round(target - before, 4)
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    adjustment_type = "INCREASE" if delta > 0 else "DECREASE" if delta < 0 else "NO_CHANGE"
    result: dict[str, Any] = {
        "committed": False,
        "canCommit": abs(delta) > 0.00005,
        "location": location,
        "itemName": item_name,
        "inventoryItemCode": payload.inventory_item_code,
        "unit": unit,
        "balanceBefore": before,
        "targetBalance": target,
        "adjustmentQty": abs(delta),
        "adjustmentDelta": delta,
        "adjustmentType": adjustment_type,
        "reason": payload.reason,
    }
    if abs(delta) <= 0.00005:
        result.update({"noChange": True})
        return result
    if not payload.commit:
        return result

    qty = abs(delta)
    from_location = "MANUAL_ADJUSTMENT" if delta > 0 else location
    to_location = location if delta > 0 else "MANUAL_ADJUSTMENT"
    canonical = {
        "location": location,
        "item_name": item_name,
        "inventory_item_code": payload.inventory_item_code,
        "unit": unit,
        "before": before,
        "target": target,
        "delta": delta,
        "reason": payload.reason,
        "actor": payload.actor,
        "occurred_at": occurred_at.isoformat(),
    }
    source_key = "manual-stock-edit:" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    notes = json.dumps({
        "reason": payload.reason or "Koreksi manual stok gudang",
        "actor": payload.actor,
        "balance_before": before,
        "target_balance": target,
        "delta": delta,
    }, ensure_ascii=False)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from inventory_movements where source_key=%s", (source_key,))
            duplicate = cur.fetchone()
            if duplicate:
                result.update({"committed": True, "duplicate": True, "movementId": duplicate["id"], "sourceKey": source_key})
                return result
            cur.execute(
                """insert into inventory_movements(
                     movement_type,item_code,item_name,qty,unit,from_location,to_location,
                     occurred_at,source_type,source_key,source_ref,notes
                   ) values ('MANUAL_ADJUSTMENT',%s,%s,%s,%s,%s,%s,%s,
                             'MANUAL_STOCK_EDIT',%s,%s,%s)
                   returning id""",
                (
                    (payload.inventory_item_code or None),
                    item_name,
                    qty,
                    unit,
                    from_location,
                    to_location,
                    occurred_at,
                    source_key,
                    f"manual-stock-edit:{location}",
                    notes,
                ),
            )
            movement_id = cur.fetchone()["id"]
            conn.commit()
    result.update({
        "committed": True,
        "duplicate": False,
        "movementId": movement_id,
        "sourceKey": source_key,
        "balanceAfter": target,
    })
    return result
