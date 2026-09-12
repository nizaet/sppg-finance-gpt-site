from __future__ import annotations

from copy import deepcopy
import threading
import time
from datetime import date
from typing import Any

from backend import po_reminder_v4_api as _v4

_ORIGINAL_PROJECTION_LOOKUP = _v4._projection_lookup
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 64
_LOCK = threading.RLock()
_CACHE: dict[tuple[str, date], tuple[float, tuple[dict[tuple[str, str], float], str]]] = {}
_KEY_LOCKS: dict[tuple[str, date], threading.Lock] = {}
_INSTALLED = False
EPSILON = 0.0001


def _copy_result(value: tuple[dict[tuple[str, str], float], str]) -> tuple[dict[tuple[str, str], float], str]:
    # The reminder code treats the projection lookup as read-only, but return a
    # fresh dict so a future caller cannot accidentally mutate the shared cache.
    return dict(value[0]), value[1]


def _prune(now: float) -> None:
    expired = [key for key, (stored_at, _) in _CACHE.items() if now - stored_at >= _CACHE_TTL_SECONDS]
    for key in expired:
        _CACHE.pop(key, None)
        key_lock = _KEY_LOCKS.get(key)
        if key_lock is not None and not key_lock.locked():
            _KEY_LOCKS.pop(key, None)
    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: len(_CACHE) - _CACHE_MAX_ENTRIES]:
        _CACHE.pop(key, None)
        key_lock = _KEY_LOCKS.get(key)
        if key_lock is not None and not key_lock.locked():
            _KEY_LOCKS.pop(key, None)


def projection_lookup(site: str, distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    """Short-lived single-flight cache for an explicitly requested projection.

    po_reminders_v4 already runs its required dates in a bounded worker pool.
    Do not start an additional seven-day prefetch here: nested workers created
    projections the request did not need and overloaded Railway/PostgreSQL. This
    cache only deduplicates the exact site/date requested by v4.
    """
    key = (str(site or "").upper().strip(), distribution_date)
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return _copy_result(cached[1])
        key_lock = _KEY_LOCKS.setdefault(key, threading.Lock())

    with key_lock:
        now = time.monotonic()
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and now - cached[0] < _CACHE_TTL_SECONDS:
                return _copy_result(cached[1])

        result = _ORIGINAL_PROJECTION_LOOKUP(*key)
        with _LOCK:
            _CACHE[key] = (time.monotonic(), _copy_result(result))
            _prune(time.monotonic())
        return _copy_result(result)


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


def _latest_active_plan_totals(site: str, dates: set[date]) -> dict[tuple[date, str, str], dict[str, Any]]:
    """Return only the newest ACTIVE planning snapshot for each site/date.

    The PO Planner reads the newest active snapshot for a distribution date. The
    reminder engine historically summed every ACTIVE snapshot, which can happen
    when calculator/import source systems coexist. That made the reminder demand
    larger than the PO Planner demand even though the PO had already deducted
    dapur stock correctly.
    """
    normalized_site = str(site or "").upper().strip()
    if normalized_site not in {"MAJA", "CEMPLANG"} or not dates or not _v4.database_ready():
        return {}

    start = min(dates)
    end = max(dates)
    with _v4.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with latest as (
                    select distinct on (upper(site), distribution_date)
                           id, upper(site) as site, distribution_date
                    from planning_snapshots
                    where status='ACTIVE'
                      and upper(site)=%s
                      and distribution_date between %s and %s
                    order by upper(site), distribution_date, created_at desc, id desc
                )
                select l.id as snapshot_id, l.distribution_date,
                       psi.item_name, psi.unit, coalesce(psi.planned_qty,0) as planned_qty
                from latest l
                join planning_snapshot_items psi on psi.planning_snapshot_id=l.id
                where coalesce(psi.planned_qty,0)>0
                order by l.distribution_date, psi.id
                """,
                (normalized_site, start, end),
            )
            rows = cur.fetchall()

    totals: dict[tuple[date, str, str], dict[str, Any]] = {}
    for row in rows:
        distribution = _as_date(row.get("distribution_date"))
        if distribution not in dates:
            continue
        type_code, unit = _v4._stock_key(row.get("item_name"), row.get("unit"))
        key = (distribution, type_code, unit)
        target = totals.setdefault(key, {
            "planned_qty": 0.0,
            "item_names": set(),
            "snapshot_id": row.get("snapshot_id"),
        })
        target["planned_qty"] = round(float(target["planned_qty"]) + float(row.get("planned_qty") or 0), 4)
        name = str(row.get("item_name") or "").strip()
        if name:
            target["item_names"].add(name)
    return totals


def _coverage_stage(detail: dict[str, Any], recommended: float) -> str:
    completed = float(detail.get("completed_po_qty") or 0)
    finalized = float(detail.get("finalized_po_qty") or 0)
    draft = float(detail.get("draft_po_qty") or 0)
    if completed + EPSILON >= recommended:
        return "DONE"
    if completed + finalized + EPSILON >= recommended:
        return "READY_TO_SEND"
    if completed + finalized + draft + EPSILON >= recommended:
        return "DRAFT_NEEDS_FINAL"
    return "OPEN"


def _reconcile_latest_plan(payload: dict[str, Any], site: str, target: date) -> dict[str, Any]:
    """Align reminder math with the PO Planner: latest plan -> dapur stock -> PO.

    The authoritative order is:
      net PO need = max(0, latest planning qty - projected local dapur stock)
      remaining   = max(0, net PO need - exact saved PO coverage)

    KOPERASI stock is not used here. Exact saved PO coverage remains the v4 result,
    already matched by site + distribution date + item type + unit.
    """
    items = payload.get("items") or []
    dates: set[date] = set()
    for item in items:
        for detail in item.get("requirement_details") or []:
            distribution = _as_date(detail.get("distribution_date"))
            if distribution:
                dates.add(distribution)
    if not dates:
        return payload

    totals = _latest_active_plan_totals(site, dates)
    if not totals:
        return payload

    result = deepcopy(payload)
    reconciled_items: list[dict[str, Any]] = []
    corrected_details = 0
    removed_stock_covered = 0

    for item in result.get("items") or []:
        original_details = item.get("requirement_details") or []
        if not original_details:
            reconciled_items.append(item)
            continue

        details: list[dict[str, Any]] = []
        stages: list[str] = []
        missing_names: set[str] = set()
        missing_dates: set[date] = set()

        for detail in original_details:
            distribution = _as_date(detail.get("distribution_date"))
            type_code = str(detail.get("stock_type_code") or "").upper().strip()
            unit = _v4.canonical_unit(detail.get("unit")) or ""
            latest = totals.get((distribution, type_code, unit)) if distribution else None
            latest_planned = round(float((latest or {}).get("planned_qty") or 0), 4)
            projected_stock = round(float(detail.get("projected_stock_qty") or 0), 4)
            recommended = max(0.0, round(latest_planned - projected_stock, 4))

            # No net PO need means the local dapur stock already covers the newest
            # planning requirement. It must disappear from the PO action reminder.
            if recommended <= EPSILON:
                removed_stock_covered += 1
                corrected_details += 1
                continue

            covered = round(float(detail.get("covered_po_qty") or 0), 4)
            remaining = max(0.0, round(recommended - covered, 4))
            stage = _coverage_stage(detail, recommended)
            names = sorted((latest or {}).get("item_names") or detail.get("item_names") or [])

            if remaining <= EPSILON:
                ordering_state = "COVERED"
            elif float(detail.get("completed_po_qty") or 0) > EPSILON:
                ordering_state = "ORDERED_PARTIAL"
            elif covered > EPSILON:
                ordering_state = "IN_APP_PARTIAL"
            else:
                ordering_state = "NOT_ORDERED"

            if latest_planned != round(float(detail.get("planned_qty") or 0), 4) or remaining != round(float(detail.get("remaining_po_qty") or 0), 4):
                corrected_details += 1

            detail.update({
                "item_names": names,
                "planned_qty": latest_planned,
                "recommended_po_qty": recommended,
                "remaining_po_qty": remaining,
                "coverage_stage": stage,
                "ordering_state": ordering_state,
                "planning_snapshot_id": (latest or {}).get("snapshot_id"),
                "planning_source_model": "LATEST_ACTIVE_SNAPSHOT_PER_SITE_DATE",
            })
            details.append(detail)
            stages.append(stage)
            if remaining > EPSILON:
                missing_names.update(names)
                if distribution:
                    missing_dates.add(distribution)

        # If every requirement is covered by local dapur stock, the reminder row
        # itself is obsolete. This is the key behavior requested by operations.
        if not details:
            continue

        po_date = _as_date(item.get("po_date")) or target
        item["requirement_details"] = details
        item["missing_item_names"] = sorted(missing_names)
        item["missing_distribution_dates"] = sorted(missing_dates)
        item["item_names"] = sorted({name for detail in details for name in (detail.get("item_names") or []) if name})
        item["item_count"] = len(item["item_names"])
        item["reminder_status"] = _v4._group_stage(stages, po_date, target)
        item["planning_source_model"] = "LATEST_ACTIVE_SNAPSHOT_PER_SITE_DATE"
        reconciled_items.append(item)

    result["items"] = reconciled_items
    result["planningSourceModel"] = "LATEST_ACTIVE_SNAPSHOT_PER_SITE_DATE"
    result["planningReconciledDetailCount"] = corrected_details
    result["stockCoveredDetailRemovedCount"] = removed_stock_covered
    result["poReminderFormula"] = "LATEST_PLAN_MINUS_LOCAL_DAPUR_STOCK_MINUS_EXACT_PO_COVERAGE"
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _v4._projection_lookup = projection_lookup

    # The browser uses /po-reminders-v3. Patch the v4 function reference imported
    # by v3 so its cache stores the corrected latest-plan payload. This keeps all
    # later legacy/override/shortage reconciliation passes working unchanged.
    from backend import po_reminder_v3_api as _v3

    original_v4 = _v3.po_reminders_v4

    def latest_plan_v4(site: str = "", as_of: date | None = None, horizon_days: int = 2) -> dict[str, Any]:
        target = as_of or date.today()
        raw = original_v4(site=site, as_of=as_of, horizon_days=horizon_days)
        return _reconcile_latest_plan(raw, site, target)

    latest_plan_v4._sppg_latest_plan_reconciler = True  # type: ignore[attr-defined]
    _v3.po_reminders_v4 = latest_plan_v4
    _INSTALLED = True
