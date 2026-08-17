from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.po_reminder_completed_shortage import enrich_completed_po_shortages
from backend.po_reminder_legacy_po_reconcile import reconcile_legacy_completed_pos
from backend.po_reminder_operational_reconcile import reconcile_operational_po_reminders
from backend.po_reminder_tools_api import apply_reminder_overrides
from backend.po_reminder_v4_api import po_reminders_v4

router = APIRouter(tags=["po-reminder-v3"])

_OVERRIDE_TIMING_STATUSES = {"OVERDUE", "DUE_TODAY", "UPCOMING", "SHORTAGE_REVIEW"}


@router.get("/po-reminders-v3")
def po_reminders_v3(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Stable reminder endpoint with operational reconciliation.

    v4 remains authoritative for planning, projected stock, lead time, and exact
    PO coverage. Compatibility passes reconcile operator-confirmed WIKIAN/Tempe
    behavior, repair legacy single-date completed-PO item coverage, move true
    completed-PO residuals into SHORTAGE_REVIEW, and finally apply explicit
    reminder-only manual resolutions. No pass mutates planning, PO, receiving,
    invoice, payment, or physical SO source data.
    """
    target = as_of or date.today()
    payload = po_reminders_v4(site=site, as_of=target, horizon_days=horizon_days)
    payload = reconcile_operational_po_reminders(payload, site, target)
    payload = reconcile_legacy_completed_pos(payload, site, target)
    payload = enrich_completed_po_shortages(payload, site)

    # Keep the stable v3 compatibility contract exact for non-operational/mock
    # payloads and avoid querying the override table when no reminder can have an
    # operator resolution. SHORTAGE_REVIEW needs a key so the operator can mark
    # the residual as checked/intentional after a PO was already completed.
    if not any(
        str(item.get("reminder_status") or "").upper() in _OVERRIDE_TIMING_STATUSES
        for item in (payload.get("items") or [])
    ):
        return payload
    return apply_reminder_overrides(payload, site, target)
