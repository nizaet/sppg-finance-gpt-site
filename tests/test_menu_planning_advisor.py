from datetime import date

from backend.menu_planning_advisor_api import _build_week_draft, router


def _snapshot(snapshot_id, distribution_date, menu_name, recipe, fruit, price=10000):
    return {
        "id": snapshot_id,
        "distribution_date": distribution_date,
        "payload": {
            "planName": menu_name,
            "porsiKecil": 100,
            "porsiBesar": 20,
            "recipes": [{"name": recipe}],
        },
        "items": [
            {"item_name": "Bumbu halus", "category_code": "SAYUR_BUAH_BUMBU", "planned_qty": 6, "unit": "kg", "planning_price": price, "preferred_vendor_code": "HOLIL"},
            {"item_name": fruit, "category_code": "SAYUR_BUAH_BUMBU", "planned_qty": 120, "unit": "pcs", "planning_price": 2000, "preferred_vendor_code": "HOLIL"},
        ],
    }


def test_menu_advisor_exposes_only_read_only_routes():
    methods = {
        method
        for route in router.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    }
    assert methods == {"GET"}


def test_weekly_draft_scales_historical_bumbu_and_varies_menu_and_fruit():
    snapshots = [
        _snapshot(1, date(2026, 7, 1), "Sate ayam", "Sate Ayam", "Jeruk Medan"),
        _snapshot(2, date(2026, 7, 2), "Ikan bumbu kuning", "Ikan Bumbu Kuning", "Pisang"),
    ]
    result = _build_week_draft(
        site="MAJA", week_start=date(2026, 8, 3), days=3, snapshots=snapshots,
        target_pm=240, pagu_per_pm=5000, knowledge=[],
    )

    days = result["days"]
    assert result["readOnly"] is True
    assert result["draftOnly"] is True
    assert result["summary"]["proposedDays"] == 3
    assert days[0]["menuTitle"] != days[1]["menuTitle"]
    assert days[0]["fruitNames"] != days[1]["fruitNames"]
    # Source recipe is for 120 PM; 240 PM doubles the historical bumbu.
    assert days[0]["materials"][0]["quantity"] == 12
    assert days[0]["estimatedPerPm"] is not None


def test_existing_day_is_never_replaced_and_missing_price_blocks_pagu_claim():
    existing = _snapshot(9, date(2026, 8, 3), "Sudah direncanakan", "Menu Lama", "Apel", price=None)
    history = _snapshot(1, date(2026, 7, 1), "Sate ayam", "Sate Ayam", "Jeruk Medan")
    result = _build_week_draft(
        site="MAJA", week_start=date(2026, 8, 3), days=2, snapshots=[existing, history],
        target_pm=120, pagu_per_pm=5000, knowledge=[],
    )

    assert result["days"][0]["state"] == "EXISTING"
    assert result["days"][0]["menuTitle"] == "Sudah direncanakan"
    assert result["days"][0]["withinPagu"] is None
    assert result["automationBoundary"]["canCreateOrEditCalculator"] is False
