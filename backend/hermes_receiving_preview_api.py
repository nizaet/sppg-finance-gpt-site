from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.gpt_bridge_api import require_gpt_auth
from backend.hermes_receiving_guard import (
    issue_receiving_confirmation_token,
    receiving_commit_eligible,
    token_ttl_seconds,
)
from backend.operational_api import WhatsAppReceiptIn
from backend.receiving_multi_po_runtime_patch import receive_from_whatsapp_v2


router = APIRouter(prefix="/gpt/hermes-read", tags=["hermes-read-only"])


class HermesReceivingPreviewIn(BaseModel):
    """Read-only receiving input.

    Deliberately has no `commit` field. Hermes can ask the operational resolver
    to reconcile a message against live PO/receipt state, but cannot mutate
    receiving, inventory, PO status, finance, or any other production record.
    """

    model_config = ConfigDict(extra="forbid")

    site: Literal["MAJA", "CEMPLANG"]
    text: str = Field(min_length=1, max_length=20000)
    vendor_code: str | None = Field(default=None, max_length=100)
    purchase_order_id: int | None = Field(default=None, ge=1)
    received_at: datetime | None = None
    source_external_id: str | None = Field(default=None, max_length=300)
    reporter: str | None = Field(default=None, max_length=200)


def _token_payload(payload: HermesReceivingPreviewIn) -> dict[str, Any]:
    return payload.model_dump(mode="json", exclude_none=True)


@router.post("/receiving-preview")
def preview_receiving_multi_po(
    payload: HermesReceivingPreviewIn,
    _auth: None = Depends(require_gpt_auth),
) -> dict[str, Any]:
    """Reconcile receiving text against live PO state without writing anything.

    The production multi-PO resolver is reused with `commit=False` forced by the
    server. A short-lived confirmation token is returned only when the current
    preview is unambiguous, can safely commit, and has no over-receipt.
    """

    operational_payload = WhatsAppReceiptIn(
        site=payload.site,
        text=payload.text,
        vendor_code=payload.vendor_code,
        purchase_order_id=payload.purchase_order_id,
        received_at=payload.received_at,
        source_external_id=payload.source_external_id,
        reporter=payload.reporter,
        commit=False,
    )
    result = receive_from_whatsapp_v2(operational_payload)

    if bool(result.get("committed")):
        raise RuntimeError("read-only Hermes receiving preview attempted an operational commit")

    eligible = receiving_commit_eligible(result)
    confirmation_token = issue_receiving_confirmation_token(_token_payload(payload)) if eligible else None

    return {
        **result,
        "committed": False,
        "readOnly": True,
        "sourceOfTruth": "SPPG Core PostgreSQL",
        "operationalMutation": False,
        "resolver": "multi-po-v2",
        "commitEligible": eligible,
        "confirmationToken": confirmation_token,
        "confirmationExpiresInSeconds": token_ttl_seconds() if confirmation_token else None,
        "commitBlockReason": None if eligible else (
            "over-receipt requires manual review" if bool(result.get("canCommit")) else "resolver is not safe to commit"
        ),
    }
