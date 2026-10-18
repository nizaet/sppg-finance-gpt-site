from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection
from backend.inventory_api import commit_receipt_stock
from backend.operational_api import require_db

router = APIRouter(tags=["po-receiving-confirmation"])

_RECEIVABLE_STATUSES = {"FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
_EPSILON = 0.0001


class ActualReceiptLine(BaseModel):
    purchase_order_item_id: int
    received_qty: Decimal = Field(gt=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    expected_received_qty: Decimal = Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)


class PoReceivingConfirmIn(BaseModel):
    mode: Literal["ALL", "SELECTED", "ACTUAL"] = "ALL"
    items: list[ActualReceiptLine] = Field(default_factory=list)
    request_id: UUID = Field(default_factory=uuid4)
    purchase_order_item_ids: list[int] = Field(default_factory=list)
    reporter: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)


def _load_po(cur: Any, purchase_order_id: int, *, lock: bool = False) -> dict[str, Any]:
    cur.execute(
        """
        select po.id,po.po_code,po.site,po.vendor_code,po.status,po.production_cycle_id,
               pc.distribution_date
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where po.id=%s
        """ + (" for update of po" if lock else ""),
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
    """Record actual arrival quantities or confirm the remaining PO quantities.

    This action is independent from the old red delivery warning. It writes a
    normal goods_receipt + goods_receipt_items, updates inventory idempotently,
    and derives the PO status from cumulative accepted receipts.
    """
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id, lock=True)
            items = _load_items(cur, purchase_order_id)
            by_id = {int(item["id"]): item for item in items}

            if payload.mode == "ACTUAL":
                requested = [line.purchase_order_item_id for line in payload.items]
                if not requested or len(set(requested)) != len(requested):
                    raise HTTPException(400, "Isi barang dan jumlah aktual tanpa item ganda")
                if any(value not in by_id for value in requested):
                    raise HTTPException(400, "Barang bukan milik PO ini")
                source_key = f"po-receive-actual:{purchase_order_id}:{payload.request_id}"
                cur.execute("select id from goods_receipts where source_key=%s", (source_key,))
                duplicate = cur.fetchone()
                if duplicate:
                    return {"saved": True, "receiptCreated": False, "receiptId": duplicate["id"],
                            "message": "Penerimaan ini sudah tersimpan.", "items": items}
                for line in payload.items:
                    if Decimal(str(by_id[line.purchase_order_item_id]["receivedQty"])) != line.expected_received_qty:
                        raise HTTPException(409, "Penerimaan berubah. Refresh dan periksa jumlah terbaru sebelum menyimpan.")
                selected = [dict(by_id[line.purchase_order_item_id], remainingQty=line.received_qty) for line in payload.items]
            elif payload.mode == "SELECTED":
                requested = sorted({int(value) for value in payload.purchase_order_item_ids})
                unknown = [value for value in requested if value not in by_id]
                if unknown:
                    raise HTTPException(400, f"item PO tidak ditemukan: {unknown}")
                selected = [by_id[value] for value in requested]
            else:
                selected = items

            remaining = [item for item in selected if float(item.get("remainingQty") or 0) > (0 if payload.mode == "ACTUAL" else _EPSILON)]
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

            if payload.mode != "ACTUAL":
                source_key = f"po-receive-confirm:{purchase_order_id}:{payload.request_id}"
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
                        f"CONFIRM-{po['po_code']}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                        source_key,
                        source_key,
                        payload.reporter,
                        payload.note or ("Konfirmasi semua barang sesuai PO" if payload.mode == "ALL" else "Konfirmasi item barang sesuai PO"),
                    ),
                )
                receipt_id = int(cur.fetchone()["id"])
                for item in remaining:
                    amount = Decimal(str(item["remainingQty"]))
                    cur.execute(
                        """
                        insert into goods_receipt_items(
                          goods_receipt_id,purchase_order_item_id,received_qty,rejected_qty,accepted_qty,unit,
                          quality_status,notes,reported_item_name,po_qty_snapshot,variance_qty,match_confidence,match_method
                        ) values (%s,%s,%s,0,%s,%s,'ACCEPTED',%s,%s,%s,%s,1,'po_receiving_confirmation')
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
                            amount - Decimal(str(item.get("poQty") or 0)),
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
    _invalidate_stock(str(po["site"]))

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


class ReceiptCorrectionLine(BaseModel):
    receipt_item_id: int
    received_qty: Decimal = Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    rejected_qty: Decimal = Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    expected_received_qty: Decimal = Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    expected_rejected_qty: Decimal = Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    expected_updated_at: datetime | None = None


class ReceiptCorrectionIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    request_id: UUID
    reason: str = Field(min_length=3, max_length=1000)
    items: list[ReceiptCorrectionLine] = Field(min_length=1)


def _invalidate_stock(site):
    from backend.po_reminder_projection_cache_patch import invalidate_projection_cache
    invalidate_projection_cache(site)


@router.patch("/goods-receipts/{receipt_id}/quantities")
def correct_goods_receipt(receipt_id: int, payload: ReceiptCorrectionIn) -> dict[str, Any]:
    """Correct actual receipt quantities; preserve evidence, audit, and stock history.

    This corrects the historical arrival at its original effective timestamp.
    It is not a return today or a new stock count. Invoice snapshots stay intact.
    """
    require_db()
    if len(payload.reason.strip()) < 3:
        raise HTTPException(400, "Alasan koreksi wajib diisi")
    ids = [line.receipt_item_id for line in payload.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "Item koreksi ganda")
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select purchase_order_id from goods_receipts where id=%s", (receipt_id,))
            found = cur.fetchone()
            if not found:
                raise HTTPException(404, "Penerimaan tidak ditemukan")
            po = _load_po(cur, found["purchase_order_id"], lock=True)
            if str(po["site"]).upper() != payload.site:
                raise HTTPException(400, "Penerimaan bukan milik dapur ini")
            cur.execute("select id from goods_receipts where id=%s for update", (receipt_id,))
            request_key = f"receipt-correction:{receipt_id}:{payload.request_id}"
            cur.execute("select details from event_audit_log where action='CORRECT_GOODS_RECEIPT' and details->>'requestKey'=%s", (request_key,))
            prior = cur.fetchone()
            if prior:
                reviewed = prior["details"]
                submitted = {line.receipt_item_id: (str(line.received_qty.normalize()), str(line.rejected_qty.normalize())) for line in payload.items}
                original = {c["receiptItemId"]: (str(Decimal(c["after"]["receivedQty"]).normalize()), str(Decimal(c["after"]["rejectedQty"]).normalize())) for c in reviewed["changes"]}
                if submitted != original or reviewed["reason"] != payload.reason.strip():
                    raise HTTPException(409, "Kunci permintaan sudah digunakan untuk koreksi berbeda. Buka ulang formulir.")
                return {**reviewed, "duplicate": True, "saved": True}
            cur.execute("""select gri.*,poi.item_name,poi.item_code from goods_receipt_items gri
                           left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
                           where gri.goods_receipt_id=%s order by gri.id for update of gri""", (receipt_id,))
            rows = {int(row["id"]): dict(row) for row in cur.fetchall()}
            changes = []
            for line in payload.items:
                row = rows.get(line.receipt_item_id)
                if row is None:
                    raise HTTPException(400, "Barang bukan milik penerimaan ini")
                old_received = Decimal(str(row.get("received_qty") or 0))
                old_rejected = Decimal(str(row.get("rejected_qty") or 0))
                if ((old_received, old_rejected) != (line.expected_received_qty, line.expected_rejected_qty)
                    or (line.expected_updated_at is not None and line.expected_updated_at != row.get("updated_at"))):
                    raise HTTPException(409, "Penerimaan sudah berubah. Buka ulang koreksi dan periksa jumlah terbaru.")
                if line.rejected_qty > line.received_qty:
                    raise HTTPException(400, "Jumlah reject tidak boleh melebihi jumlah datang")
                if (old_received, old_rejected) == (line.received_qty, line.rejected_qty):
                    continue
                accepted = line.received_qty - line.rejected_qty
                old_accepted = Decimal(str(row.get("accepted_qty") if row.get("accepted_qty") is not None else old_received - old_rejected))
                changes.append({"receiptItemId": line.receipt_item_id, "itemName": row.get("item_name") or row.get("reported_item_name"),
                    "unit": row.get("unit"), "before": {"receivedQty": str(old_received), "rejectedQty": str(old_rejected), "acceptedQty": str(old_accepted)},
                    "after": {"receivedQty": str(line.received_qty), "rejectedQty": str(line.rejected_qty), "acceptedQty": str(accepted)},
                    "stockDelta": str(accepted - old_accepted)})
            if not changes:
                return {"saved": True, "changed": False, "message": "Tidak ada perubahan jumlah."}
            # Finish any missing original posting before writing compensating deltas.
            commit_receipt_stock(cur, receipt_id, payload.site)
            for change in changes:
                row = rows[change["receiptItemId"]]
                accepted = Decimal(change["after"]["acceptedQty"])
                cur.execute("""update goods_receipt_items set received_qty=%s,rejected_qty=%s,accepted_qty=%s,
                    variance_qty=%s-coalesce(po_qty_snapshot,0),quality_status=%s,updated_at=now() where id=%s""",
                    (change["after"]["receivedQty"],change["after"]["rejectedQty"],accepted,change["after"]["receivedQty"],
                     "REJECTED" if accepted == 0 else "PARTIAL" if Decimal(change["after"]["rejectedQty"]) > 0 else "ACCEPTED", row["id"]))
                delta = Decimal(change["stockDelta"])
                if delta:
                    # Reuse original locations/identity/time so later master changes and
                    # newer physical SO anchors cannot create a second stock identity.
                    cur.execute("select * from inventory_movements where source_key=%s", (f"goods-receipt-stock:{receipt_id}:{row['id']}",))
                    movement = cur.fetchone()
                    if movement:
                        origin, destination = movement["from_location"], movement["to_location"]
                        when, name, code, unit = movement["occurred_at"], movement["item_name"], movement["item_code"], movement["unit"]
                    else:
                        # A formerly zero-quantity row has no original stock movement.
                        cur.execute("select received_at from goods_receipts where id=%s", (receipt_id,))
                        when = cur.fetchone()["received_at"]
                        origin, destination = ("KOPERASI" if po["vendor_code"] == "KOPERASI" else f"VENDOR:{po['vendor_code']}"), payload.site
                        name, code, unit = change["itemName"], row.get("item_code"), row.get("unit")
                        # Reserve the original idempotency key; replay must not repost the corrected quantity.
                        cur.execute("""insert into inventory_movements(movement_type,item_code,item_name,qty,unit,from_location,to_location,
                            production_cycle_id,occurred_at,source_type,source_key,source_ref,notes)
                            values ('RECEIPT_CORRECTION',%s,%s,0,%s,%s,%s,%s,%s,'GOODS_RECEIPT',%s,%s,%s)""",
                            (code,name,unit,origin,destination,po["production_cycle_id"],when,f"goods-receipt-stock:{receipt_id}:{row['id']}",f"receipt:{receipt_id}","Zero original quantity; correction follows"))
                    if delta < 0:
                        origin, destination = destination, origin
                    cur.execute("""insert into inventory_movements(movement_type,item_code,item_name,qty,unit,from_location,to_location,
                        production_cycle_id,occurred_at,source_type,source_key,source_ref,notes)
                        values ('RECEIPT_CORRECTION',%s,%s,%s,%s,%s,%s,%s,%s,'GOODS_RECEIPT',%s,%s,%s)""",
                        (code,name,abs(delta),unit,origin,destination,po["production_cycle_id"],when,
                         f"{request_key}:{row['id']}",f"receipt:{receipt_id}",payload.reason.strip()))
            cur.execute("update goods_receipts set updated_at=now() where id=%s", (receipt_id,))
            updated_items = _load_items(cur, po["id"])
            new_status = _po_status(updated_items) or ("SENT" if po.get("status") in {"RECEIVED", "PARTIAL_RECEIVED"} else po["status"])
            cur.execute("update purchase_orders set status=%s,updated_at=now() where id=%s", (new_status, po["id"]))
            cur.execute("""select distinct vi.id from vendor_invoices vi left join vendor_invoice_items vii on vii.vendor_invoice_id=vi.id
                where vi.goods_receipt_id=%s or vii.goods_receipt_item_id=any(%s)""", (receipt_id, ids))
            invoice_ids = [r["id"] for r in cur.fetchall()]
            result = {"saved": True,"changed": True,"receiptId": receipt_id,"purchaseOrderId": po["id"],"site": payload.site,
                "requestKey": request_key,"reason": payload.reason.strip(),"changes": changes,"purchaseOrderStatus": new_status,
                "linkedInvoiceIds": invoice_ids,"invoiceReviewRequired": bool(invoice_ids),
                "message": "Koreksi penerimaan tersimpan. Selisih stok disesuaikan; invoice dan pembayaran tidak diubah."}
            cur.execute("insert into event_audit_log(action,actor,details) values ('CORRECT_GOODS_RECEIPT','operations-ui',%s::jsonb)", (json.dumps(result),))
            conn.commit()
    _invalidate_stock(payload.site)
    return result
