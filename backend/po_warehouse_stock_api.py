from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.db import connection
from backend.inventory_projection_v2_api import inventory_balances_v2, _type_key
from backend.inventory_api import load_item_matchers, classify_item
from backend.inventory_unit_conversion import convert_inventory_quantity
from backend.operational_api import require_db
from backend.stock_opname_parser import canonical_unit
from backend.po_reminder_projection_cache_patch import invalidate_projection_cache

router = APIRouter(tags=["po-warehouse-stock"])


class PoWarehouseStockIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    planning_snapshot_item_id: int
    distribution_date: date
    cooking_date: date
    unit: str = Field(min_length=1, max_length=30)
    target_balance: Decimal = Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    expected_actual_balance: Decimal = Field(max_digits=18, decimal_places=4, allow_inf_nan=False)
    request_id: UUID

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value):
        return canonical_unit(value)


def resolve_stock_row(items, type_code, unit):
    rows = [row for row in items if row.get("stock_type_code") == type_code and row.get("unit") == unit]
    if len(rows) > 1:
        raise HTTPException(409, "Identitas stok belum tunggal; periksa master/alias dan satuan di Gudang.")
    return rows[0] if rows else {}


@router.post("/inventory/po-stock-confirmation")
def confirm_po_warehouse_stock(payload: PoWarehouseStockIn) -> dict[str, Any]:
    """Save the PO's before-cooking count; never rewrite SO, ordered qty or planning.

    Today's plan remains to be consumed. The frontend must reload the server
    projection for the selected target cooking day before enabling PO creation.
    """
    require_db()
    today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    if payload.cooking_date < today or payload.cooking_date > payload.distribution_date:
        raise HTTPException(400, "Koreksi stok PO hanya untuk masak hari ini atau sesudahnya, sebelum distribusi.")
    source_key = f"po-warehouse-stock:{payload.site}:{payload.request_id}"
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"po-warehouse-stock:{payload.site}",))
            cur.execute("select details from event_audit_log where action='PO_WAREHOUSE_STOCK' and details->>'sourceKey'=%s", (source_key,))
            prior = cur.fetchone()
            if prior:
                result = prior["details"]
                if (result["planningItemId"] != payload.planning_snapshot_item_id or Decimal(str(result["targetBalance"])) != payload.target_balance
                    or result["cookingDate"] != str(payload.cooking_date) or result["unit"] != payload.unit):
                    raise HTTPException(409, "Kunci simpan sudah digunakan untuk perubahan berbeda. Buka ulang stok.")
                return {**result, "duplicate": True}
            cur.execute("""select psi.item_name,psi.unit,ps.site,ps.distribution_date,ps.status
                from planning_snapshot_items psi join planning_snapshots ps on ps.id=psi.planning_snapshot_id
                where psi.id=%s for share of ps,psi""", (payload.planning_snapshot_item_id,))
            plan = cur.fetchone()
            if not plan or plan["site"].upper() != payload.site or plan["distribution_date"] != payload.distribution_date:
                raise HTTPException(400, "Barang planning bukan milik dapur/tanggal ini.")
            if plan["status"] != "ACTIVE":
                raise HTTPException(409, "Planning telah berubah. Tarik ulang planning sebelum menyimpan stok.")
            masters = load_item_matchers(cur, payload.site)
            match = classify_item(plan["item_name"], masters)
            if match.get("classificationStatus") == "AMBIGUOUS":
                raise HTTPException(409, "Nama barang memiliki beberapa master. Periksa alias di Gudang lebih dahulu.")
            type_code, unit, label, _ = _type_key(plan["item_name"], payload.unit, masters)
            _, planning_unit, _, _ = _type_key(plan["item_name"], plan["unit"], masters)
            if payload.unit not in {canonical_unit(plan["unit"]), planning_unit}:
                raise HTTPException(400, "Gunakan satuan barang pada planning; perbaiki satuan di Gudang bila diperlukan.")
            def operational_amount(value):
                amount, converted_unit, _ = convert_inventory_quantity(value, payload.unit, {**match, "stockTypeCode": type_code})
                if converted_unit != unit:
                    raise HTTPException(409, "Konversi satuan stok belum dapat dipastikan.")
                return Decimal(str(amount)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            target = operational_amount(payload.target_balance)
            expected = operational_amount(payload.expected_actual_balance)
            projection = inventory_balances_v2(site=payload.site, search="", limit=1000, for_date=payload.distribution_date,
                cooking_date=payload.cooking_date, same_day_stock_before_cooking=True)
            row = resolve_stock_row(projection.get("items") or [], type_code, unit)
            before = Decimal(str(row.get("actual_balance") or 0))
            if before != expected:
                raise HTTPException(409, "Stok gudang sudah berubah. Tarik ulang stok dan periksa jumlah aktual.")
            delta = target - before
            name = row.get("item_name") or label
            notes = {"source": "PO_PLANNER_STOCK_CHECK", "stock_check_timing": "BEFORE_COOKING",
                "balance_before": str(before), "target_balance": str(target),
                "planning_item_id": payload.planning_snapshot_item_id, "cooking_date": str(payload.cooking_date)}
            origin, destination = ("MANUAL_ADJUSTMENT", payload.site) if delta > 0 else (payload.site, "MANUAL_ADJUSTMENT")
            if delta == 0:
                origin = destination = payload.site
            cur.execute("""insert into inventory_movements(movement_type,item_code,item_name,qty,unit,from_location,to_location,
                occurred_at,source_type,source_key,source_ref,notes)
                values ('MANUAL_STOCK_CORRECTION',%s,%s,%s,%s,%s,%s,now(),'MANUAL_STOCK_EDIT',%s,%s,%s) returning id""",
                (row.get("inventory_item_code"),name,abs(delta),unit,origin,destination,source_key,
                 f"planning-item:{payload.planning_snapshot_item_id}",json.dumps(notes)))
            movement_id = cur.fetchone()["id"]
            result = {"committed": True, "site": payload.site, "planningItemId": payload.planning_snapshot_item_id,
                "itemName": name, "unit": payload.unit, "warehouseUnit": unit, "balanceBefore": str(before), "targetBalance": str(payload.target_balance),
                "storedTargetBalance": str(target),
                "adjustmentDelta": str(delta), "movementId": movement_id, "sourceKey": source_key,
                "cookingDate": str(payload.cooking_date), "stockCheckTiming": "BEFORE_COOKING"}
            cur.execute("insert into event_audit_log(action,actor,details) values ('PO_WAREHOUSE_STOCK','operations-ui',%s::jsonb)", (json.dumps(result),))
            conn.commit()
    invalidate_projection_cache(payload.site)
    return result
