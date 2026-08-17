from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from backend.po_reminder_completed_shortage import enrich_completed_po_shortages
from backend.po_reminder_legacy_po_reconcile import reconcile_legacy_completed_pos
from backend.po_reminder_operational_reconcile import reconcile_operational_po_reminders
from backend.po_reminder_tools_api import apply_reminder_overrides
from backend.po_reminder_v4_api import po_reminders_v4

router = APIRouter(tags=["po-reminder-v3"])

_OVERRIDE_TIMING_STATUSES = {"OVERDUE", "DUE_TODAY", "UPCOMING", "SHORTAGE_REVIEW"}
_DONE_STATUSES = {"DONE"}

# The PO action screen is an operational queue, not a long-range forecast.
# Keep it aligned with the requested scope: overdue lookback from v4 + H-0 + tomorrow.
# This also prevents the browser's 20s SPPG Core API timeout caused by scanning 21 days
# plus every vendor lead-time projection.
PO_ACTION_HORIZON_DAYS = 2


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _hide_resolved_rows(payload: dict[str, Any], target: date) -> dict[str, Any]:
    """Return only rows that still require an operator action.

    The reminder endpoint backs the "PO yang Harus Dikerjakan" screen. Rows that
    are DONE or closed by an override must no longer stay visible in the action
    queue, even though the underlying PO/audit history remains in the PO table.
    """
    items = payload.get("items") or []
    visible: list[dict[str, Any]] = []
    hidden = 0
    for item in items:
        status = str(item.get("reminder_status") or "").upper()
        if status in _DONE_STATUSES or item.get("reminder_override"):
            hidden += 1
            continue
        visible.append(item)

    result = dict(payload)
    result["items"] = visible
    result["hiddenResolvedCount"] = hidden

    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    future_actionable = actionable | {"UPCOMING"}
    tomorrow = target + timedelta(days=1)
    result["dueCount"] = sum(
        1 for item in visible
        if (_as_date(item.get("po_date")) or date.max) <= target
        and str(item.get("reminder_status") or "").upper() in actionable
    )
    result["tomorrowCount"] = sum(
        1 for item in visible
        if _as_date(item.get("po_date")) == tomorrow
        and str(item.get("reminder_status") or "").upper() in future_actionable
    )
    result["overdueCount"] = sum(
        1 for item in visible
        if (_as_date(item.get("po_date")) or date.max) < target
        and str(item.get("reminder_status") or "").upper() == "OVERDUE"
    )
    result["shortageReviewCount"] = sum(
        1 for item in visible
        if str(item.get("reminder_status") or "").upper() == "SHORTAGE_REVIEW"
    )
    return result


@router.get("/po-reminders-v3")
def po_reminders_v3(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=PO_ACTION_HORIZON_DAYS, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Stable reminder endpoint with operational reconciliation.

    v4 remains authoritative for planning, projected stock, lead time, and exact
    PO coverage. Compatibility passes reconcile operator-confirmed WIKIAN/Tempe
    behavior, repair legacy single-date completed-PO item coverage, move true
    completed-PO residuals into SHORTAGE_REVIEW, and finally apply explicit
    reminder-only manual resolutions. No pass mutates planning, PO, receiving,
    invoice, payment, or physical SO source data.

    The UI for "PO yang Harus Dikerjakan" must stay fast and focused on action:
    overdue rows, rows due today, and tomorrow. If an older frontend still sends a
    wider horizon such as 21 days, clamp it here instead of making the operator
    wait for a long reminder/projection scan.
    """
    target = as_of or date.today()
    effective_horizon_days = min(max(int(horizon_days or PO_ACTION_HORIZON_DAYS), 1), PO_ACTION_HORIZON_DAYS)

    payload = po_reminders_v4(site=site, as_of=target, horizon_days=effective_horizon_days)
    payload = reconcile_operational_po_reminders(payload, site, target)
    payload = reconcile_legacy_completed_pos(payload, site, target)
    payload = enrich_completed_po_shortages(payload, site)

    payload["requestedHorizonDays"] = horizon_days
    payload["effectiveHorizonDays"] = effective_horizon_days
    payload["coverageLabel"] = "terlambat 7 hari + hari ini + besok"

    # Keep the stable v3 compatibility contract exact for non-operational/mock
    # payloads and avoid querying the override table when no reminder can have an
    # operator resolution. SHORTAGE_REVIEW needs a key so the operator can mark
    # the residual as checked/intentional after a PO was already completed.
    if any(
        str(item.get("reminder_status") or "").upper() in _OVERRIDE_TIMING_STATUSES
        for item in (payload.get("items") or [])
    ):
        payload = apply_reminder_overrides(payload, site, target)
    return _hide_resolved_rows(payload, target)
