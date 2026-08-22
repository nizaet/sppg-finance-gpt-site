from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.gpt_bridge_api import require_gpt_auth
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


@router.post("/receiving-preview")
def preview_receiving_multi_po(
    payload: HermesReceivingPreviewIn,
    _auth: None = Depends(require_gpt_auth),
) -> dict[str, Any]:
    """Reconcile receiving text against live PO state without writing anything.

    The production multi-PO resolver is reused with `commit=False` forced by the
    server. This lets Hermes inspect all relevant active POs, cumulative receipt
    quantities, item matches, outstanding quantities, and proposed allocations
    while preserving PostgreSQL as the source of truth.
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

    # Defensive guard: this route must never report an operational commit.
    if bool(result.get("committed")):
        raise RuntimeError("read-only Hermes receiving preview attempted an operational commit")

    return {
        **result,
        "committed": False,
        "readOnly": True,
        "sourceOfTruth": "SPPG Core PostgreSQL",
        "operationalMutation": False,
        "resolver": "multi-po-v2",
    }
