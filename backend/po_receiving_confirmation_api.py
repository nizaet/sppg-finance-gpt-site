from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection
from backend.inventory_api import commit_receipt_stock
from backend.operational_api import require_db

router = APIRouter(tags=["po-receiving-confirmation"])

_RECEIVABLE_STATUSES = {"FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
_EPSILON = 0.0001


class PoReceivingConfirmIn(BaseModel):
    mode: Literal["ALL", "SELECTED"] = "ALL"
    purchase_order_item_ids: list[int] = Field(default_factory=list)
    reporter: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)


def _load_po(cur: Any, purchase_order_id: int) -> dict[str, Any]:
    cur.execute(
        """
        select po.id,po.po_code,po.site,po.vendor_code,po.status,po.production_cycle_id,
               pc.distribution_date
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where po.id=%s
        """,
        (purchase_order_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "purchase order not found")
    po = dict(row)
    if str(po.get("status") or "").upper() not in _RECEIVABLE_STATUSES:
        raise HTTPException(409, "PO harus FINAL/SENT sebelum penerimaan dapat dikonfirmasi")
    return po


def _load_items(cur: Any, purchase_order_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        select poi.id,poi.item_code,poi.item_name,poi.po_qty,poi.unit,
               coalesce(sum(gri.accepted_qty),0) as received_qty
        from purchase_order_items poi
        left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
        where poi.purchase_order_id=%s
        group by poi.id,poi.item_code,poi.item_name,poi.po_qty,poi.unit
        order by poi.id
        """,
        (purchase_order_id,),
    )
    items: list[dict[str, Any]] = []
    for row in cur.fetchall():
        item = dict(row)
        ordered = float(item.get("po_qty") or 0)
        received = float(item.get("received_qty") or 0)
        remaining = max(0.0, round(ordered - received, 4))
        item.update(
            {
                "poQty": ordered,
                "receivedQty": round(received, 4),
                "remainingQty": remaining,
                "complete": remaining <= _EPSILON,
            }
        )
        items.append(item)
    return items


def _po_status(items: list[dict[str, Any]]) -> str:
    if items and all(bool(item.get("complete")) for item in items):
        return "RECEIVED"
    if any(float(item.get("receivedQty") or 0) > _EPSILON for item in items):
        return "PARTIAL_RECEIVED"
    return ""


@router.get("/purchase-orders/{purchase_order_id}/receiving-confirmation")
def po_receiving_confirmation(purchase_order_id: int) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            items = _load_items(cur, purchase_order_id)
    complete_count = sum(1 for item in items if item["complete"])
    return {
        "purchaseOrderId": po["id"],
        "poCode": po["po_code"],
        "site": po["site"],
        "vendorCode": po["vendor_code"],
        "status": po["status"],
        "itemCount": len(items),
        "completeCount": complete_count,
        "remainingCount": len(items) - complete_count,
        "allReceived": bool(items) and complete_count == len(items),
        "items": items,
    }


@router.post("/purchase-orders/{purchase_order_id}/receiving-confirmation")
def confirm_po_receiving(purchase_order_id: int, payload: PoReceivingConfirmIn) -> dict[str, Any]:
    """Confirm all or selected PO lines as received exactly as ordered.

    This action is independent from the old red delivery warning. It writes a
    normal goods_receipt + goods_receipt_items, updates inventory idempotently,
    and derives the PO status from cumulative accepted receipts.
    """
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            items = _load_items(cur, purchase_order_id)
            by_id = {int(item["id"]): item for item in items}

            if payload.mode == "SELECTED":
                requested = sorted({int(value) for value in payload.purchase_order_item_ids})
                unknown = [value for value in requested if value not in by_id]
                if unknown:
                    raise HTTPException(400, f"item PO tidak ditemukan: {unknown}")
                selected = [by_id[value] for value in requested]
            else:
                selected = items

            remaining = [item for item in selected if float(item.get("remainingQty") or 0) > _EPSILON]
            if not remaining:
                current_status = _po_status(items) or str(po.get("status") or "")
                return {
                    "saved": True,
                    "receiptCreated": False,
                    "purchaseOrderId": po["id"],
                    "poCode": po["po_code"],
                    "purchaseOrderStatus": current_status,
                    "message": "Item yang dipilih sudah tercatat diterima.",
                    "items": items,
                }

            signature = ",".join(str(item["id"]) for item in remaining)
            source_key = "po-receive-confirm:" + hashlib.sha256(
                f"{po['id']}|{signature}|".encode("utf-8")
            ).hexdigest()
            cur.execute("select id from goods_receipts where source_key=%s", (source_key,))
            duplicate = cur.fetchone()

            if duplicate:
                receipt_id = int(duplicate["id"])
                stock = commit_receipt_stock(cur, receipt_id, str(po["site"]))
            else:
                cur.execute(
                    """
                    insert into goods_receipts(
                      purchase_order_id,receipt_code,received_at,source_type,source_external_id,source_key,
                      reporter,raw_text,match_status,match_confidence,confirmed_at
                    ) values (%s,%s,now(),'PO_CONFIRMATION',%s,%s,%s,%s,'CONFIRMED',1,now())
                    returning id
                    """,
                    (
                        po["id"],
                        f"CONFIRM-{po['po_code']}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                        source_key,
                        source_key,
                        payload.reporter,
                        payload.note or ("Konfirmasi semua barang sesuai PO" if payload.mode == "ALL" else "Konfirmasi item barang sesuai PO"),
                    ),
                )
                receipt_id = int(cur.fetchone()["id"])
                for item in remaining:
                    amount = float(item["remainingQty"])
                    cur.execute(
                        """
                        insert into goods_receipt_items(
                          goods_receipt_id,purchase_order_item_id,received_qty,rejected_qty,accepted_qty,unit,
                          quality_status,notes,reported_item_name,po_qty_snapshot,variance_qty,match_confidence,match_method
                        ) values (%s,%s,%s,0,%s,%s,'ACCEPTED',%s,%s,%s,0,1,'po_receiving_confirmation')
                        """,
                        (
                            receipt_id,
                            item["id"],
                            amount,
                            amount,
                            item.get("unit"),
                            payload.note,
                            item.get("item_name"),
                            item.get("poQty"),
                        ),
                    )
                stock = commit_receipt_stock(cur, receipt_id, str(po["site"]))

            updated_items = _load_items(cur, purchase_order_id)
            new_status = _po_status(updated_items)
            if new_status:
                cur.execute(
                    "update purchase_orders set status=%s,updated_at=now() where id=%s",
                    (new_status, purchase_order_id),
                )
            else:
                new_status = str(po.get("status") or "")
            conn.commit()

    return {
        "saved": True,
        "receiptCreated": True,
        "receiptId": receipt_id,
        "purchaseOrderId": po["id"],
        "poCode": po["po_code"],
        "purchaseOrderStatus": new_status,
        "confirmedItemIds": [int(item["id"]) for item in remaining],
        "stockInserted": stock["inserted"],
        "stockDuplicates": stock["duplicates"],
        "message": "Penerimaan barang tersimpan dari PO.",
        "items": updated_items,
    }
