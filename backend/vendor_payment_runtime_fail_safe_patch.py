from __future__ import annotations

import logging
import re
import uuid

from fastapi import HTTPException

from backend import vendor_payment_duplicate_guard_patch as duplicate_guard
from backend import vendor_payment_evidence_api as evidence_api
from backend import vendor_payment_override_api as payment_api

_INSTALLED = False
_ORIGINAL_UPDATE_SYNC_STATUS = payment_api._update_sync_status
_ORIGINAL_EVIDENCE_COMMIT = evidence_api.commit_vendor_payment_evidence
logger = logging.getLogger(__name__)


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


def _safe_evidence_commit(payload):
    """Never turn an upload/ledger exception into an opaque browser HTTP 500."""
    try:
        return _ORIGINAL_EVIDENCE_COMMIT(payload)
    except HTTPException:
        raise
    except Exception as exc:
        reference = uuid.uuid4().hex[:12]
        logger.exception("vendor payment evidence commit failed; reference=%s", reference)
        detail = re.sub(r"(?:postgres(?:ql)?|https?)://[^\\s'\\\"]+", "[redacted-url]", str(exc or "")).strip()
        detail = detail[:500] or type(exc).__name__
        raise HTTPException(
            503,
            f"Pencatatan bukti pembayaran belum selesai (ref {reference}): {type(exc).__name__}: {detail}",
        ) from exc


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
    evidence_api.commit_vendor_payment_evidence = _safe_evidence_commit

    # FastAPI copied these routes before runtime patches are installed. Rebind
    # both the source router and the live application route used by the SPA.
    from backend.app import app as fastapi_app
    for route in [*evidence_api.router.routes, *fastapi_app.routes]:
        path = str(getattr(route, "path", ""))
        if path != "/commit" and not path.endswith("/vendor-payments/evidence/commit"):
            continue
        route.endpoint = _safe_evidence_commit
        if getattr(route, "dependant", None) is not None:
            route.dependant.call = _safe_evidence_commit

    _INSTALLED = True
