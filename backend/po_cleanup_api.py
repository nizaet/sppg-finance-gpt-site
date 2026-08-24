from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.db import connection, database_ready

router = APIRouter(tags=["po-cleanup"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


@router.delete("/purchase-orders/{purchase_order_id}")
def delete_cancelled_test_or_historical_purchase_order(purchase_order_id: int) -> dict[str, Any]:
    """Permanently remove only cleanup-safe PO records.

    Allowed directly: DRAFT, CANCELLED, HISTORICAL_IMPORTED, or explicit TEST-*.
    Normal finalized/sent production evidence remains protected. TEST-* may also
    clean its test receiving + stock movements. Any vendor invoice/payable blocks
    deletion so financial evidence is never removed accidentally.
    """
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select id,po_code,revision_no,status,supersedes_po_id
                   from purchase_orders where id=%s""",
                (purchase_order_id,),
            )
            po = cur.fetchone()
            if not po:
                raise HTTPException(404, "purchase order not found")

            status = str(po.get("status") or "").upper()
            po_code = str(po.get("po_code") or "").upper().strip()
            is_test = po_code.startswith("TEST-")
            allowed_statuses = {"DRAFT", "CANCELLED", "HISTORICAL_IMPORTED"}
            if status not in allowed_statuses and not is_test:
                raise HTTPException(
                    409,
                    "Hanya PO DRAFT, CANCELLED, HISTORICAL_IMPORTED, atau PO berkode TEST-* yang dapat dihapus permanen",
                )

            cur.execute(
                "select exists(select 1 from vendor_invoices where purchase_order_id=%s) as used",
                (purchase_order_id,),
            )
            if bool(cur.fetchone()["used"]):
                raise HTTPException(
                    409,
                    "PO sudah memiliki invoice/payable vendor dan tidak dapat dihapus permanen",
                )

            cur.execute(
                "select id from goods_receipts where purchase_order_id=%s order by id",
                (purchase_order_id,),
            )
            receipt_ids = [int(row["id"]) for row in cur.fetchall()]
            if receipt_ids and not is_test:
                raise HTTPException(
                    409,
                    "PO sudah memiliki penerimaan dan tidak dapat dihapus permanen. Hanya PO TEST-* yang boleh membersihkan data penerimaan test.",
                )

            if receipt_ids:
                cur.execute(
                    """delete from inventory_movements
                       where source_type='GOODS_RECEIPT'
                         and (
                           source_ref = any(%s)
                           or source_key like any(%s)
                         )""",
                    (
                        [f"receipt:{rid}" for rid in receipt_ids],
                        [f"goods-receipt-stock:{rid}:%" for rid in receipt_ids],
                    ),
                )
                cur.execute(
                    "delete from goods_receipt_items where goods_receipt_id=any(%s)",
                    (receipt_ids,),
                )
                cur.execute(
                    "delete from goods_receipts where id=any(%s)",
                    (receipt_ids,),
                )

            # Preserve revision ancestry for any later revision that pointed to
            # the row being deleted.
            cur.execute(
                "update purchase_orders set supersedes_po_id=%s where supersedes_po_id=%s",
                (po.get("supersedes_po_id"), purchase_order_id),
            )

            cur.execute(
                "select id from purchase_order_coverage where purchase_order_id=%s",
                (purchase_order_id,),
            )
            coverage_ids = [int(row["id"]) for row in cur.fetchall()]
            if coverage_ids:
                cur.execute(
                    "delete from purchase_order_coverage_items where purchase_order_coverage_id=any(%s)",
                    (coverage_ids,),
                )
                cur.execute(
                    "delete from purchase_order_coverage where id=any(%s)",
                    (coverage_ids,),
                )

            cur.execute(
                "delete from purchase_order_items where purchase_order_id=%s",
                (purchase_order_id,),
            )
            cur.execute("delete from purchase_orders where id=%s", (purchase_order_id,))
        conn.commit()

    return {
        "deleted": True,
        "purchaseOrderId": purchase_order_id,
        "poCode": po["po_code"],
        "revisionNo": po["revision_no"],
        "previousStatus": status,
        "testData": is_test,
        "deletedGoodsReceipts": len(receipt_ids),
    }
