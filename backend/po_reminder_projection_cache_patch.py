from __future__ import annotations

import threading
import time
from datetime import date

from backend import po_reminder_v4_api as _v4

_ORIGINAL_PROJECTION_LOOKUP = _v4._projection_lookup
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 64
_LOCK = threading.RLock()
_CACHE: dict[tuple[str, date], tuple[float, tuple[dict[tuple[str, str], float], str]]] = {}
_KEY_LOCKS: dict[tuple[str, date], threading.Lock] = {}
_INSTALLED = False


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


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _v4._projection_lookup = projection_lookup
    _INSTALLED = True
