from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.gpt_bridge_api import require_gpt_auth
from backend.hermes_receiving_guard import (
    receiving_commit_eligible,
    validate_receiving_confirmation_token,
)
from backend.operational_api import WhatsAppReceiptIn
from backend.receiving_multi_po_runtime_patch import receive_from_whatsapp_v2


router = APIRouter(prefix="/gpt/hermes-actions", tags=["hermes-actions"])


class HermesReceivingCommitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: Literal["MAJA", "CEMPLANG"]
    text: str = Field(min_length=1, max_length=20000)
    vendor_code: str | None = Field(default=None, max_length=100)
    purchase_order_id: int | None = Field(default=None, ge=1)
    received_at: datetime | None = None
    source_external_id: str | None = Field(default=None, max_length=300)
    reporter: str | None = Field(default=None, max_length=200)
    confirmation_token: str = Field(min_length=20, max_length=500)
    confirmation: Literal["COMMIT TRUE"]


def _preview_payload(payload: HermesReceivingCommitIn) -> dict[str, Any]:
    return payload.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"confirmation_token", "confirmation"},
    )


def _operational_payload(payload: HermesReceivingCommitIn, *, commit: bool) -> WhatsAppReceiptIn:
    return WhatsAppReceiptIn(
        site=payload.site,
        text=payload.text,
        vendor_code=payload.vendor_code,
        purchase_order_id=payload.purchase_order_id,
        received_at=payload.received_at,
        source_external_id=payload.source_external_id,
        reporter=payload.reporter,
        commit=commit,
    )


@router.post("/receiving-commit")
def commit_hermes_receiving(
    payload: HermesReceivingCommitIn,
    _auth: None = Depends(require_gpt_auth),
) -> dict[str, Any]:
    """Commit a receiving event only after a safe, short-lived Hermes preview.

    The token is bound to the exact preview payload. Before mutation, the live
    multi-PO resolver is run again with commit=False so changed PO/receipt state
    or a newly unsafe allocation blocks the write.
    """

    preview_payload = _preview_payload(payload)
    validate_receiving_confirmation_token(preview_payload, payload.confirmation_token)

    current = receive_from_whatsapp_v2(_operational_payload(payload, commit=False))
    if bool(current.get("committed")):
        raise RuntimeError("Hermes receiving preflight unexpectedly committed")
    if not receiving_commit_eligible(current):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "receiving changed or is no longer safe to commit; run preview again",
                "preview": current,
            },
        )

    result = receive_from_whatsapp_v2(_operational_payload(payload, commit=True))
    if not bool(result.get("committed")):
        raise HTTPException(status_code=502, detail="production receiving runtime did not confirm commit")

    return {
        **result,
        "committed": True,
        "operationalMutation": True,
        "mutationType": "RECEIVING",
        "humanConfirmation": True,
        "confirmation": "COMMIT TRUE",
        "sourceOfTruth": "SPPG Core PostgreSQL",
        "resolver": "multi-po-v2",
    }
