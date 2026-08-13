from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready

router = APIRouter(prefix="/v1", tags=["inventory"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def norm(value: str) -> str:
    return " ".join((value or "").lower().strip().split())


def stock_balance(cur, site: str, item_name: str) -> float:
    cur.execute(
        """
        select coalesce(sum(
          case
            when upper(coalesce(to_location,''))=upper(%s) then qty
            when upper(coalesce(from_location,''))=upper(%s) then -qty
            else 0
          end
        ),0) as balance
        from inventory_movements
        where lower(trim(item_name))=lower(trim(%s))
          and (upper(coalesce(to_location,''))=upper(%s) or upper(coalesce(from_location,''))=upper(%s))
        """,
        (site, site, item_name, site, site),
    )
    return float(cur.fetchone()["balance"] or 0)


class ReceiptToStockIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    goods_receipt_id: int
    commit: bool = False


@router.post("/inventory/from-receipt")
def inventory_from_receipt(payload: ReceiptToStockIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select gr.id,gr.received_at,po.site,po.vendor_code,po.production_cycle_id,po.po_code
                   from goods_receipts gr join purchase_orders po on po.id=gr.purchase_order_id
                   where gr.id=%s""",
                (payload.goods_receipt_id,),
            )
            receipt = cur.fetchone()
            if not receipt:
                raise HTTPException(404, "goods receipt not found")
            if str(receipt["site"]).upper() != payload.site.upper():
                raise HTTPException(400, "site does not match goods receipt")
            cur.execute(
                """select gri.id as receipt_item_id,coalesce(gri.accepted_qty,gri.received_qty,0) as qty,
                          gri.unit,poi.item_code,coalesce(poi.item_name,gri.reported_item_name) as item_name
                   from goods_receipt_items gri
                   left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
                   where gri.goods_receipt_id=%s order by gri.id""",
                (payload.goods_receipt_id,),
            )
            rows = cur.fetchall()
            preview = []
            for row in rows:
                key = f"goods-receipt-stock:{payload.goods_receipt_id}:{row['receipt_item_id']}"
                preview.append({
                    "sourceKey": key,
                    "itemName": row["item_name"],
                    "qty": float(row["qty"] or 0),
                    "unit": row["unit"],
                    "fromLocation": f"VENDOR:{receipt['vendor_code']}",
                    "toLocation": payload.site,
                })
            if not payload.commit:
                return {"committed": False, "canCommit": bool(preview), "goodsReceiptId": payload.goods_receipt_id, "items": preview}

            inserted = 0
            duplicates = 0
            for row, item in zip(rows, preview):
                cur.execute("select id from inventory_movements where source_key=%s", (item["sourceKey"],))
                if cur.fetchone():
                    duplicates += 1
                    continue
                cur.execute(
                    """insert into inventory_movements(
                         movement_type,item_code,item_name,qty,unit,from_location,to_location,production_cycle_id,
                         occurred_at,source_type,source_key,source_ref,notes
                       ) values ('PURCHASE_RECEIPT',%s,%s,%s,%s,%s,%s,%s,coalesce(%s,now()),'GOODS_RECEIPT',%s,%s,%s)""",
                    (
                        row["item_code"], row["item_name"], row["qty"], row["unit"],
                        item["fromLocation"], payload.site, receipt["production_cycle_id"], receipt["received_at"],
                        item["sourceKey"], f"receipt:{payload.goods_receipt_id}", f"PO {receipt['po_code']}",
                    ),
                )
                inserted += 1
            conn.commit()
            return {
                "committed": True,
                "goodsReceiptId": payload.goods_receipt_id,
                "inserted": inserted,
                "duplicates": duplicates,
                "items": preview,
            }


class UsageIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    item_name: str = Field(min_length=1)
    qty: float = Field(gt=0)
    unit: str
    occurred_at: datetime | None = None
    source_ref: str | None = None
    commit: bool = False


@router.post("/inventory/usage")
def inventory_usage(payload: UsageIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            before = stock_balance(cur, payload.site, payload.item_name)
            after = before - payload.qty
            result = {
                "committed": False,
                "site": payload.site,
                "itemName": payload.item_name,
                "balanceBefore": before,
                "usageQty": payload.qty,
                "balanceAfter": after,
                "unit": payload.unit,
                "stockWarning": after < 0,
            }
            if not payload.commit:
                return result
            canonical = {
                "site": payload.site,
                "item": norm(payload.item_name),
                "qty": payload.qty,
                "unit": payload.unit,
                "occurred_at": (payload.occurred_at or datetime.now(timezone.utc)).isoformat(),
                "source_ref": payload.source_ref,
            }
            key = "inventory-usage:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            cur.execute("select id from inventory_movements where source_key=%s", (key,))
            duplicate = cur.fetchone()
            if duplicate:
                result.update({"committed": True, "duplicate": True, "movementId": duplicate["id"]})
                return result
            cur.execute(
                """insert into inventory_movements(
                     movement_type,item_name,qty,unit,from_location,to_location,occurred_at,
                     source_type,source_key,source_ref
                   ) values ('PRODUCTION_USAGE',%s,%s,%s,%s,'PRODUCTION',coalesce(%s,now()),'ACTUAL_USAGE',%s,%s)
                   returning id""",
                (payload.item_name, payload.qty, payload.unit, payload.site, payload.occurred_at, key, payload.source_ref),
            )
            movement_id = cur.fetchone()["id"]
            conn.commit()
            result.update({"committed": True, "duplicate": False, "movementId": movement_id})
            return result


@router.get("/inventory/balance")
def inventory_balance(site: str, item: str = Query(min_length=1)) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            return {"site": site.upper(), "itemName": item, "balance": stock_balance(cur, site, item)}


@router.get("/inventory/requirement-preview")
def inventory_requirement_preview(
    site: str,
    item: str = Query(min_length=1),
    plannedQty: float = Query(ge=0),
    unit: str = "kg",
) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            available = stock_balance(cur, site, item)
    purchase_needed = max(float(plannedQty) - max(available, 0), 0)
    return {
        "site": site.upper(),
        "itemName": item,
        "plannedQty": float(plannedQty),
        "stockAvailable": available,
        "purchaseNeeded": purchase_needed,
        "unit": unit,
        "financeTransactionCreated": False,
    }
