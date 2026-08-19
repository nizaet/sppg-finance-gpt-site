from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from backend import po_reminder_v4_api as _v4

_ORIGINAL_PROJECTION_LOOKUP = _v4._projection_lookup
_CACHE_TTL_SECONDS = 20.0
_CACHE_MAX_ENTRIES = 96
_PREFETCH_DAYS = 7
_MAX_WORKERS = 4
_LOCK = threading.RLock()
_CACHE: dict[tuple[str, date], tuple[float, tuple[dict[tuple[str, str], float], str]]] = {}
_KEY_LOCKS: dict[tuple[str, date], threading.Lock] = {}
_INFLIGHT: dict[tuple[str, date], Future] = {}
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="po-projection")
_INSTALLED = False


def _copy_result(value: tuple[dict[tuple[str, str], float], str]) -> tuple[dict[tuple[str, str], float], str]:
    # The reminder code treats the projection lookup as read-only, but return a
    # fresh dict so a future caller cannot accidentally mutate the shared cache.
    return dict(value[0]), value[1]


def _prune(now: float) -> None:
    expired = [key for key, (stored_at, _) in _CACHE.items() if now - stored_at >= _CACHE_TTL_SECONDS]
    for key in expired:
        _CACHE.pop(key, None)
    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: len(_CACHE) - _CACHE_MAX_ENTRIES]:
        _CACHE.pop(key, None)


def _compute_and_store(key: tuple[str, date]) -> tuple[dict[tuple[str, str], float], str]:
    site, distribution_date = key
    try:
        result = _ORIGINAL_PROJECTION_LOOKUP(site, distribution_date)
        with _LOCK:
            _CACHE[key] = (time.monotonic(), _copy_result(result))
            _prune(time.monotonic())
        return _copy_result(result)
    finally:
        with _LOCK:
            _INFLIGHT.pop(key, None)


def _schedule(key: tuple[str, date]) -> Future | None:
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return None
        existing = _INFLIGHT.get(key)
        if existing is not None:
            return existing
        future = _EXECUTOR.submit(_compute_and_store, key)
        _INFLIGHT[key] = future
        return future


def _schedule_window(site: str, distribution_date: date) -> None:
    # Reminder candidates are normally clustered over the coming week because
    # operational lead times are H-1..H-4. Prefetching only this bounded window
    # avoids the former N x sequential projection latency without opening an
    # unbounded number of PostgreSQL connections.
    for offset in range(0, max(0, int(_PREFETCH_DAYS)) + 1):
        _schedule((site, distribution_date + timedelta(days=offset)))


def projection_lookup(site: str, distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    """Bounded concurrent single-flight cache for expensive stock projections.

    Stock arithmetic is unchanged: every cache miss still calls the original
    inventory projection function. The optimization only evaluates nearby dates
    concurrently (max four workers), because po_reminders_v4 otherwise evaluates
    each independent distribution date serially and can exceed the UI timeout.
    """
    key = (str(site or "").upper().strip(), distribution_date)
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return _copy_result(cached[1])

    _schedule_window(key[0], distribution_date)

    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return _copy_result(cached[1])
        future = _INFLIGHT.get(key)

    if future is None:
        # Defensive fallback if a future completed between the checks above.
        future = _schedule(key)
        if future is None:
            with _LOCK:
                cached = _CACHE.get(key)
                if cached:
                    return _copy_result(cached[1])
            return _ORIGINAL_PROJECTION_LOOKUP(*key)

    try:
        return _copy_result(future.result())
    except Exception:
        # Preserve previous fail-soft reminder behaviour. The underlying v4
        # projection lookup already converts ordinary projection failures to
        # PROJECTION_UNAVAILABLE; this protects against executor-level failures.
        return {}, "PROJECTION_UNAVAILABLE"


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _v4._projection_lookup = projection_lookup
    _INSTALLED = True
