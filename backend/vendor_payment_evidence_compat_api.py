from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.vendor_payment_evidence_api import (
    EvidenceCommitIn,
    EvidenceInspectIn,
    commit_vendor_payment_evidence,
    inspect_vendor_payment_evidence,
)

router = APIRouter(tags=["vendor-payment-evidence-compat"])


@router.post("/vendor-payments/evidence/inspect")
def inspect_payment_evidence_compat(payload: EvidenceInspectIn) -> dict[str, Any]:
    return inspect_vendor_payment_evidence(payload)


@router.post("/vendor-payments/evidence/commit")
def commit_payment_evidence_compat(payload: EvidenceCommitIn) -> dict[str, Any]:
    return commit_vendor_payment_evidence(payload)
