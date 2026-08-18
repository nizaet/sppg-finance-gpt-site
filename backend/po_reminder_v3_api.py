from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from threading import Lock
from time import monotonic, perf_counter
from typing import Any

from fastapi import APIRouter, Query

from backend.item_taxonomy import item_family
from backend.po_reminder_completed_shortage import enrich_completed_po_shortages
from backend.po_reminder_legacy_po_reconcile import reconcile_legacy_completed_pos
from backend.po_reminder_operational_reconcile import reconcile_operational_po_reminders
from backend.po_reminder_override_fallback import apply_fallback_reminder_overrides
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

# v4 performs taxonomy-aware projected stock calculations and may open several DB
# connections for one reminder request. Browsers can issue the same request more
# than once while mounting/re-rendering the operations page. Keep a deliberately
# tiny cache and a per-key single-flight lock so identical concurrent requests do
# not repeat that expensive work. Five seconds is short enough that PO/receiving
# state changes become visible almost immediately without special invalidation.
_V4_CACHE_TTL_SECONDS = 5.0
_v4_cache_guard = Lock()
_v4_cache: dict[tuple[str, date, int], tuple[float, dict[str, Any]]] = {}
_v4_key_locks: dict[tuple[str, date, int], Lock] = {}


def _cached_v4_payload(site: str, target: date, horizon_days: int) -> tuple[dict[str, Any], bool, float]:
    key = (str(site or "").upper().strip(), target, int(horizon_days))
    now = monotonic()

    with _v4_cache_guard:
        cached = _v4_cache.get(key)
        if cached and now - cached[0] <= _V4_CACHE_TTL_SECONDS:
            return deepcopy(cached[1]), True, 0.0
        key_lock = _v4_key_locks.setdefault(key, Lock())

    # Only requests for the exact same site/date/horizon are serialized. MAJA and
    # CEMPLANG can still calculate in parallel.
    with key_lock:
        now = monotonic()
        with _v4_cache_guard:
            cached = _v4_cache.get(key)
            if cached and now - cached[0] <= _V4_CACHE_TTL_SECONDS:
                return deepcopy(cached[1]), True, 0.0

        started = perf_counter()
        payload = po_reminders_v4(site=site, as_of=target, horizon_days=horizon_days)
        elapsed_ms = round((perf_counter() - started) * 1000.0, 1)

        with _v4_cache_guard:
            # Opportunistically purge expired entries so date-based keys cannot
            # grow forever in a long-running Railway process.
            expiry_cutoff = monotonic() - _V4_CACHE_TTL_SECONDS
            expired = [cache_key for cache_key, value in _v4_cache.items() if value[0] < expiry_cutoff]
            for cache_key in expired:
                _v4_cache.pop(cache_key, None)
                if cache_key != key:
                    _v4_key_locks.pop(cache_key, None)
            _v4_cache[key] = (monotonic(), deepcopy(payload))

        return payload, False, elapsed_ms


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


def _is_tofu_tempe_line(value: Any) -> bool:
    text = str(value or "")
    family = item_family(text)
    return family in {"TOFU", "TEMPE"} or any(token in text.lower() for token in ("tahu", "tempe"))


def _fix_maja_koperasi_tofu_tempe_h1(payload: dict[str, Any], target: date) -> dict[str, Any]:
    """Keep MAJA KOPERASI tofu/tempe reminders at H-1 from cooking.

    MAJA tahu/tempe via KOPERASI/Mungki is an H-1 operational order. A broader
    KOPERASI/dry-goods vendor rule can otherwise pull Tahu Putih into the red
    overdue bucket several days early. This compatibility pass changes only the
    reminder row timing; it does not mutate vendor rules, planning, PO, or stock.
    """
    items = payload.get("items") or []
    if not items:
        return payload

    changed = False
    adjusted: list[dict[str, Any]] = []
    for original in items:
        item = dict(original)
        site = str(item.get("site") or "").upper().strip()
        vendor = str(item.get("vendor_code") or "").upper().strip()
        names = [*(item.get("item_names") or [])]
        for detail in item.get("requirement_details") or []:
            names.extend(detail.get("item_names") or [])
        if site == "MAJA" and vendor == "KOPERASI" and any(_is_tofu_tempe_line(name) for name in names):
            cook = _as_date(item.get("cooking_date"))
            if cook is None:
                cooks = [_as_date(value) for value in (item.get("cooking_dates") or [])]
                cook = min([value for value in cooks if value is not None], default=None)
            if cook is not None:
                correct_po_date = cook - timedelta(days=1)
                old_po_date = _as_date(item.get("po_date"))
                if old_po_date != correct_po_date:
                    item["po_date"] = correct_po_date
                    item["lead_time_days_before_cooking"] = 1
                    item["reminder_timing_override"] = "MAJA_KOPERASI_TAHU_TEMPE_H1"
                    if correct_po_date < target:
                        item["reminder_status"] = "OVERDUE"
                    elif correct_po_date == target:
                        item["reminder_status"] = "DUE_TODAY"
                    elif correct_po_date == target + timedelta(days=1):
                        item["reminder_status"] = "UPCOMING"
                    changed = True
        adjusted.append(item)

    if not changed:
        return payload
    result = dict(payload)
    result["items"] = adjusted
    result["majaKoperasiTofuTempeH1Fix"] = True
    return result


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

    payload, cache_hit, compute_ms = _cached_v4_payload(site, target, effective_horizon_days)
    payload = reconcile_operational_po_reminders(payload, site, target)
    payload = reconcile_legacy_completed_pos(payload, site, target)
    payload = enrich_completed_po_shortages(payload, site)
    # Apply the MAJA KOPERASI tahu/tempe H-1 timing last so no compatibility
    # reconciliation step can overwrite it back to a broader vendor lead time.
    payload = _fix_maja_koperasi_tofu_tempe_h1(payload, target)

    payload["requestedHorizonDays"] = horizon_days
    payload["effectiveHorizonDays"] = effective_horizon_days
    payload["coverageLabel"] = "terlambat 7 hari + hari ini + besok"
    payload["v4CacheHit"] = cache_hit
    payload["v4ComputeMs"] = compute_ms

    # Keep the stable v3 compatibility contract exact for non-operational/mock
    # payloads and avoid querying the override table when no reminder can have an
    # operator resolution. SHORTAGE_REVIEW needs a key so the operator can mark
    # the residual as checked/intentional after a PO was already completed.
    if any(
        str(item.get("reminder_status") or "").upper() in _OVERRIDE_TIMING_STATUSES
        for item in (payload.get("items") or [])
    ):
        payload = apply_reminder_overrides(payload, site, target)
        payload = apply_fallback_reminder_overrides(payload, site, target)
    return _hide_resolved_rows(payload, target)
