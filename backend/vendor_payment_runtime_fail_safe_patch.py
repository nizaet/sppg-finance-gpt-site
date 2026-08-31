from __future__ import annotations

from backend import vendor_payment_duplicate_guard_patch as duplicate_guard
from backend import vendor_payment_evidence_api as evidence_api
from backend import vendor_payment_override_api as payment_api

_INSTALLED = False
_ORIGINAL_UPDATE_SYNC_STATUS = payment_api._update_sync_status


def _safe_update_sync_status(transaction_id, status, doc_id, error, evidence_uri=None):
    """Firestore bookkeeping is secondary to the committed payment.

    The vendor payment + finance transaction are committed to PostgreSQL before
    Firestore synchronization runs. A schema/config/network problem while
    recording that secondary sync status must not turn a successfully saved
    payment into HTTP 500 in the operator UI.
    """
    try:
        return _ORIGINAL_UPDATE_SYNC_STATUS(transaction_id, status, doc_id, error, evidence_uri)
    except Exception:
        return None


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Install the current itemized-finance duplicate guard first. This makes a
    # retry safe if a previous request committed PostgreSQL but failed later in
    # Firestore synchronization or response handling.
    duplicate_guard.install()

    payment_api._update_sync_status = _safe_update_sync_status

    # vendor_payment_evidence_api imported the payment function directly during
    # module import. Rebind that local name so the upload modal uses the guarded
    # implementation too, rather than bypassing the retry protection.
    evidence_api.record_vendor_payment_evidence = payment_api.record_vendor_payment_evidence

    _INSTALLED = True
