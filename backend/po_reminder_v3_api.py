from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.po_reminder_completed_shortage import enrich_completed_po_shortages
from backend.po_reminder_v4_api import po_reminders_v4

router = APIRouter(tags=["po-reminder-v3"])


@router.get("/po-reminders-v3")
def po_reminders_v3(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Compatibility endpoint backed by the strict v4 reminder engine.

    v4 remains authoritative for planning, stock projection, lead time, and exact
    shortage calculation. This compatibility layer only separates two states that
    must not be conflated: the PO workflow may already be DONE/SENT while a residual
    shortage still needs a reminder for revision/additional ordering.
    """
    payload = po_reminders_v4(site=site, as_of=as_of, horizon_days=horizon_days)
    return enrich_completed_po_shortages(payload, site)
