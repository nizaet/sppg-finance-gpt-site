from __future__ import annotations

from typing import Any

from backend import accountant_selected_plan_api as selected
from backend import calculator_planning_bridge_api as bridge

_INSTALLED = False
_ORIGINAL_SELECT = selected._select_candidate


def _select_candidate_live(site: str, distribution_date, document_id: str) -> dict[str, Any]:
    """Read the selected plan through the same resilient bridge used by discovery.

    ``_ORIGINAL_SELECT`` re-runs planning discovery for every Preview/Tarik Ulang
    request and reads Calculator dailyPlans through ``bridge._daily_plan_matches``.
    That bridge already provides the canonical scan and Firestore REST fallback
    needed by MAJA when the Firestore SDK path fails. Reusing the freshly selected
    bridge candidate keeps MAJA and CEMPLANG on the same source path instead of
    doing a second SDK-only document read for MAJA.
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
