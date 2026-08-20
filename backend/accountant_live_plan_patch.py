from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend import accountant_selected_plan_api as selected
from backend import calculator_planning_bridge_api as bridge
from backend.google_services import SITE_TARGETS, firestore_client

_INSTALLED = False
_ORIGINAL_SELECT = selected._select_candidate


def _select_candidate_live(site: str, distribution_date, document_id: str) -> dict[str, Any]:
    """Resolve the selected planning row, then re-read that exact Firestore document.

    The planning-options query is only discovery. Excel generation must never
    trust the snapshot object returned by that query because the operator may
    have edited the same daily-plan document immediately before pressing
    Preview/Tarik Ulang. Re-reading the exact document makes the Excel source
    the current persisted calculator document rather than an earlier query
    snapshot held in memory.
    """
    discovered = _ORIGINAL_SELECT(site, distribution_date, document_id)
    app_id = discovered.get("app_id")
    if not app_id:
        return discovered

    client = firestore_client(SITE_TARGETS[site]["database_id"])
    doc_ref = (
        client.collection("artifacts")
        .document(str(app_id))
        .collection("public")
        .document("data")
        .collection("dailyPlans")
        .document(document_id.strip())
    )
    snap = doc_ref.get()
    if not snap.exists:
        raise HTTPException(404, "perencanaan Kalkulator yang dipilih sudah tidak ditemukan")
    data = snap.to_dict() or {}
    if str(data.get("date") or "") != distribution_date.isoformat():
        raise HTTPException(409, "tanggal dokumen perencanaan berubah; tarik ulang daftar perencanaan")

    shopping = ((data.get("shoppingListJSON") or {}).get("shoppingList") or [])
    return {
        **discovered,
        "doc": snap,
        "data": data,
        "updated_at": bridge._plan_updated_at(data),
        "item_count": len(shopping) if isinstance(shopping, list) else 0,
        "live_refetched": True,
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    selected._select_candidate = _select_candidate_live
    _INSTALLED = True
