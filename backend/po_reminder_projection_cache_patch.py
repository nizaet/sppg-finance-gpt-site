from __future__ import annotations

import threading
import time
from copy import deepcopy
from datetime import date
from typing import Any

from backend import po_reminder_v4_api as _v4

_ORIGINAL_PROJECTION_LOOKUP = _v4._projection_lookup
_CACHE_TTL_SECONDS = 10.0
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
    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: len(_CACHE) - _CACHE_MAX_ENTRIES]:
        _CACHE.pop(key, None)


def projection_lookup(site: str, distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    """Short-lived single-flight cache for the expensive stock projection.

    This changes no stock arithmetic. It only reuses an identical site/date
    projection for a few seconds, covering duplicate frontend refreshes and the
    v3/v4 reminder endpoints hitting the same projection concurrently.
    """
    key = (str(site or "").upper().strip(), distribution_date)
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return _copy_result(cached[1])
        lock = _KEY_LOCKS.setdefault(key, threading.Lock())

    with lock:
        now = time.monotonic()
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and now - cached[0] < _CACHE_TTL_SECONDS:
                return _copy_result(cached[1])

        result = _ORIGINAL_PROJECTION_LOOKUP(site, distribution_date)
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
