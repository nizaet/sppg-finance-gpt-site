from __future__ import annotations

from datetime import datetime, timezone

from backend import vendor_payment_override_api as payment_api
from backend.db import connection, database_ready

_ORIGINAL = payment_api.record_vendor_payment_evidence
_INSTALLED = False


def _existing_result(payload: payment_api.VendorPaymentEvidenceIn, payment: dict, invoice: dict | None, *, committed: bool,
                     finance: dict | None = None, finance_inserted: bool = False) -> dict:
    unresolved = invoice is None
    warnings = []
    if unresolved:
        warnings.append(
            f"payment {payment['id']} sudah tercatat PAID_UNRECONCILED; gunakan endpoint reconcile untuk menghubungkannya ke invoice"
        )
    return {
        "committed": committed,
        "canCommit": True,
        "duplicate": True,
        "site": payment.get("site") or payload.site,
        "vendorCode": payment.get("vendor_code") or payload.vendor_code.upper().strip(),
        "amount": float(payment.get("amount") or payload.amount),
        "paidAt": payment.get("paid_at"),
        "paymentStatus": "PAID",
        "reconciliationStatus": "PAID_UNRECONCILED" if unresolved else "RECONCILED",
        "vendorPaymentId": int(payment["id"]),
        "vendorInvoiceId": invoice.get("id") if invoice else None,
        "candidatePurchaseOrderId": payment.get("candidate_purchase_order_id"),
        "candidateGoodsReceiptId": payment.get("candidate_goods_receipt_id"),
        "candidateVendorInvoiceId": payment.get("candidate_vendor_invoice_id"),
        "payableStatusAfter": invoice.get("payable_status") if invoice else None,
        "warnings": warnings,
        "financeTransactionCreated": bool(finance),
        "financeTransactionInserted": finance_inserted,
        "financeTransactionId": finance.get("transaction_id") if finance else payment.get("finance_transaction_id"),
    }


def record_vendor_payment_evidence_guarded(payload: payment_api.VendorPaymentEvidenceIn):
    """Return/recover an existing payment without ever creating a second finance row.

    Reconciliation of an already-recorded PAID_UNRECONCILED transfer is handled
    only by /vendor-payments/{payment_id}/reconcile. The stable payment row owns
    the original paid_at, so retries on later days cannot produce a new finance
    idempotency key or silently relabel the transfer as reconciled.
    """
    if not database_ready():
        return _ORIGINAL(payload)

    key = payment_api._payment_key(payload)
    with connection() as lookup_conn:
        with lookup_conn.cursor() as cur:
            cur.execute("select * from vendor_payments where source_key=%s", (key,))
            existing = cur.fetchone()
    if not existing:
        return _ORIGINAL(payload)

    with connection() as conn:
        with conn.cursor() as cur:
            # Reload under the transaction used for any recovery write.
            cur.execute("select * from vendor_payments where id=%s", (existing["id"],))
            payment = cur.fetchone()
            if not payment:
                return _ORIGINAL(payload)

            invoice = None
            if payment.get("vendor_invoice_id"):
                cur.execute(
                    """select vi.*,po.po_code from vendor_invoices vi
                       left join purchase_orders po on po.id=vi.purchase_order_id where vi.id=%s""",
                    (payment["vendor_invoice_id"],),
                )
                invoice = cur.fetchone()

            cur.execute("select * from finance_transactions where source_ref=%s order by transaction_id limit 1", (f"vendor-payment:{payment['id']}",))
            finance = cur.fetchone()
            if not payload.commit:
                return _existing_result(payload, payment, invoice, committed=False, finance=finance)

            finance_inserted = False
            if not finance:
                stored_paid_at = payment.get("paid_at") or datetime.now(timezone.utc)
                stable_payload = payload.model_copy(update={
                    "amount": float(payment.get("amount") or payload.amount),
                    "paid_at": stored_paid_at,
                    "vendor_invoice_id": payment.get("vendor_invoice_id"),
                })
                finance, finance_inserted = payment_api._finance_row(
                    cur,
                    int(payment["id"]),
                    stable_payload,
                    stored_paid_at,
                    invoice,
                )
            elif payment.get("finance_transaction_id") != finance.get("transaction_id"):
                cur.execute(
                    "update vendor_payments set finance_transaction_id=%s,updated_at=now() where id=%s",
                    (finance["transaction_id"], payment["id"]),
                )
            conn.commit()

    result = _existing_result(payload, payment, invoice, committed=True, finance=finance, finance_inserted=finance_inserted)
    if finance:
        sync_status, firestore_path, firestore_doc_id, sync_error = payment_api._sync_row(finance)
        payment_api._update_sync_status(
            finance["transaction_id"], sync_status, firestore_doc_id, sync_error, payment.get("evidence_uri") or payload.evidence_uri
        )
        result.update({
            "firestoreSyncStatus": sync_status,
            "firestoreDocument": firestore_path,
            "syncError": sync_error,
        })
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    payment_api.record_vendor_payment_evidence = record_vendor_payment_evidence_guarded
    found = False
    for route in payment_api.router.routes:
        if getattr(route, "path", "") == "/vendor-payments/record-evidence" and "POST" in (getattr(route, "methods", set()) or set()):
            route.endpoint = record_vendor_payment_evidence_guarded
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = record_vendor_payment_evidence_guarded
            found = True
            break
    if not found:
        raise RuntimeError("vendor payment evidence route not found; refusing unsafe patch install")
    _INSTALLED = True
