from datetime import date, datetime, timezone
from types import SimpleNamespace

from backend.calculator_planning_bridge_api import _planning_payload


def test_planning_bridge_combines_distinct_plans_on_same_date(monkeypatch):
    updated = datetime(2026, 8, 16, tzinfo=timezone.utc)
    candidates = [
        {
            "app_id": "sppg-maja-gpt-site",
            "doc": SimpleNamespace(id="regular"),
            "data": {"planName": "Reguler", "shoppingListJSON": {"shoppingList": [
                {"item": "Ayam fillet", "jumlah": 30, "satuan": "kg", "supplierOverride": "supplier_ayam"},
            ], "grand_total_num": 100}},
            "updated_at": updated,
            "item_count": 1,
        },
        {
            "app_id": "sppg-maja-gpt-site",
            "doc": SimpleNamespace(id="balita"),
            "data": {"planName": "Menu Kering Balita", "shoppingListJSON": {"shoppingList": [
                {"item": "Ayam fillet", "jumlah": 5, "satuan": "kg", "supplierOverride": "supplier_ayam"},
                {"item": "Beras", "jumlah": 10, "satuan": "kg", "supplierOverride": "supplier_beras"},
            ], "grand_total_num": 50}},
            "updated_at": updated,
            "item_count": 2,
        },
    ]
    monkeypatch.setattr(
        "backend.calculator_planning_bridge_api._daily_plan_matches",
        lambda site, distribution_date: (
            "sppg-maja-gpt-site", candidates[0]["doc"], candidates[0]["data"], candidates,
        ),
    )

    payload, preview = _planning_payload("MAJA", date(2026, 8, 17))

    by_name = {item.item_name: item for item in payload.items}
    assert by_name["Ayam fillet"].planned_qty == 35
    assert by_name["Ayam fillet"].source_payload["combinedPlanCount"] == 2
    assert by_name["Beras"].planned_qty == 10
    assert preview["dailyPlanDocumentIds"] == ["balita", "regular"]
    assert preview["grandTotal"] == 150
