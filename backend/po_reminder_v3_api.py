from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.po_reminder_completed_shortage import enrich_completed_po_shortages
from backend.po_reminder_operational_reconcile import reconcile_operational_po_reminders
from backend.po_reminder_tools_api import apply_reminder_overrides
from backend.po_reminder_v4_api import po_reminders_v4

router = APIRouter(tags=["po-reminder-v3"])


@router.get("/po-reminders-v3")
def po_reminders_v3(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Stable reminder endpoint with operational reconciliation.

    v4 remains authoritative for planning, projected stock, lead time, and exact
    PO coverage. Compatibility passes reconcile operator-confirmed WIKIAN/Tempe
    behavior, expose completed POs with residual shortages, and finally apply
    explicit reminder-only manual resolutions. No pass mutates planning, stock,
    PO, receiving, invoice, or payment source data.
    """
    target = as_of or date.today()
    payload = po_reminders_v4(site=site, as_of=target, horizon_days=horizon_days)
    payload = reconcile_operational_po_reminders(payload, site, target)
    payload = enrich_completed_po_shortages(payload, site)
    return apply_reminder_overrides(payload, site, target)
