from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.po_reminder_completed_shortage import enrich_completed_po_shortages
from backend.po_reminder_operational_reconcile import reconcile_operational_po_reminders
from backend.po_reminder_v4_api import po_reminders_v4

router = APIRouter(tags=["po-reminder-v3"])


@router.get("/po-reminders-v3")
def po_reminders_v3(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Stable reminder endpoint with operational reconciliation.

    v4 remains authoritative for planning, projected stock, and exact PO coverage.
    The compatibility passes then apply two operator-confirmed rules without
    mutating PO, inventory, receiving, invoice, or payment data:
    - editable dedicated Tempe lead time is read from vendor_rules;
    - genuine surplus from completed WIKIAN chicken POs closes older due shortages
      FIFO after explicit dated coverage has been reserved first.
    """
    target = as_of or date.today()
    payload = po_reminders_v4(site=site, as_of=target, horizon_days=horizon_days)
    payload = reconcile_operational_po_reminders(payload, site, target)
    return enrich_completed_po_shortages(payload, site)
