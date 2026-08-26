from datetime import date, datetime, timezone

from backend import accountant_live_plan_patch as live


class DummyDocument:
    id = "plan-maja-20260826"


def test_selected_plan_preview_reuses_fresh_bridge_candidate(monkeypatch):
    updated_at = datetime(2026, 8, 26, 6, 11, tzinfo=timezone.utc)
    data = {
        "date": "2026-08-26",
        "updatedAt": updated_at,
        "shoppingListJSON": {
            "shoppingList": [
                {"item": "Wortel", "jumlah": 10, "satuan": "kg"},
                {"item": "Jeruk Medan", "jumlah": 20, "satuan": "kg"},
            ]
        },
    }
    candidate = {
        "app_id": "sppg-maja-gpt-site",
        "doc": DummyDocument(),
        "data": data,
        "updated_at": datetime.min.replace(tzinfo=timezone.utc),
        "item_count": 0,
    }
    calls = []

    def fake_original_select(site, distribution_date, document_id):
        calls.append((site, distribution_date, document_id))
        return candidate

    monkeypatch.setattr(live, "_ORIGINAL_SELECT", fake_original_select)

    result = live._select_candidate_live("MAJA", date(2026, 8, 26), DummyDocument.id)

    assert calls == [("MAJA", date(2026, 8, 26), DummyDocument.id)]
    assert result["doc"] is candidate["doc"]
    assert result["data"] is data
    assert result["updated_at"] == updated_at
    assert result["item_count"] == 2
    assert result["live_refetched"] is True
    assert result["live_refetch_mode"] == "BRIDGE_CANONICAL_WITH_REST_FALLBACK"
