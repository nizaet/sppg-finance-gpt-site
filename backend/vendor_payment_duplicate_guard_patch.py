from __future__ import annotations

from backend import vendor_payment_override_api as payment_api
from backend.db import connection, database_ready

_ORIGINAL = payment_api.record_vendor_payment_evidence
_INSTALLED = False


def record_vendor_payment_evidence_guarded(payload: payment_api.VendorPaymentEvidenceIn):
    """A retry may not silently relabel an existing PAID_UNRECONCILED row as reconciled.

    Reconciliation of an already-recorded transfer is intentionally handled by
    /vendor-payments/{payment_id}/reconcile so no second payment is created and
    the audit trail remains explicit.
    """
    if database_ready():
        key = payment_api._payment_key(payload)
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select id,vendor_invoice_id,payment_status from vendor_payments where source_key=%s", (key,))
                existing = cur.fetchone()
        if existing and existing.get("vendor_invoice_id") is None and str(existing.get("payment_status") or "").upper() == "PAID_UNRECONCILED":
            # vendor_invoice_id is not part of the payment idempotency key. Force
            # this call to preserve the stored unresolved state; linking belongs
            # to the dedicated reconciliation endpoint.
            safe_payload = payload.model_copy(update={"vendor_invoice_id": -1})
            result = _ORIGINAL(safe_payload)
            warnings = [w for w in (result.get("warnings") or []) if "vendor_invoice_id tidak ditemukan" not in str(w)]
            warnings.append(
                f"payment {existing['id']} sudah tercatat PAID_UNRECONCILED; gunakan endpoint reconcile untuk menghubungkannya ke invoice"
            )
            result.update({
                "vendorPaymentId": int(existing["id"]),
                "vendorInvoiceId": None,
                "reconciliationStatus": "PAID_UNRECONCILED",
                "warnings": warnings,
            })
            return result
    return _ORIGINAL(payload)


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
