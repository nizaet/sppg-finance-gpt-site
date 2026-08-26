from __future__ import annotations

from typing import Any

from backend import accountant_selected_plan_api as selected
from backend import calculator_planning_bridge_api as bridge

_INSTALLED = False
_ORIGINAL_SELECT = selected._select_candidate


def _select_candidate_live(site: str, distribution_date, document_id: str) -> dict[str, Any]:
    """Read the selected plan through the same resilient bridge used by discovery.

    ``_ORIGINAL_SELECT`` is not a cached planning-options result. Every call
    executes ``_plan_candidates`` again, which in turn re-reads the Calculator
    dailyPlans collection through ``bridge._daily_plan_matches``. That bridge
    already has the bounded canonical scan and Firestore REST fallback needed by
    the MAJA default database when the Firestore SDK query/stream path fails.

    The previous patch performed a second ``DocumentReference.get()`` after that
    successful bridge read. That extra SDK-only read bypassed the bridge fallback
    and made MAJA Preview fail while CEMPLANG continued to work. Reusing the
    freshly selected bridge candidate keeps both sites on one source path and
    still guarantees Preview/Tarik Ulang reads the current persisted document.
    """
    discovered = _ORIGINAL_SELECT(site, distribution_date, document_id)
    data = discovered.get("data") or {}
    shopping = ((data.get("shoppingListJSON") or {}).get("shoppingList") or [])
    return {
        **discovered,
        "data": data,
        "updated_at": bridge._plan_updated_at(data),
        "item_count": len(shopping) if isinstance(shopping, list) else 0,
        "live_refetched": True,
        "live_refetch_mode": "BRIDGE_CANONICAL_WITH_REST_FALLBACK",
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    selected._select_candidate = _select_candidate_live
    _INSTALLED = True
