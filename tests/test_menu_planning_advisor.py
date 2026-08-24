from datetime import date

from backend.menu_planning_advisor_api import _build_week_draft, _pagu_total, _round_up_quantity, _total_pm, router


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


def test_menu_advisor_exposes_read_only_draft_routes_and_one_explicit_transfer_route():
    methods = {
        method
        for route in router.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    }
    assert methods == {"GET", "POST"}


def test_pm_is_always_small_plus_large_and_quantities_round_up():
    assert _total_pm({"porsiKecil": 1000, "porsiBesar": 43, "targetPm": 1000}) == 1043
    assert _round_up_quantity(2.001, "kg") == 2.1
    assert _round_up_quantity(10.01, "pcs") == 11


def test_split_pagu_uses_each_pm_group_without_averaging():
    # 1,000 PM kecil × 8,000 plus 43 PM besar × 10,000.
    assert _pagu_total(1000, 43, 8000, 10000) == 8_430_000


def test_weekly_draft_scales_historical_bumbu_and_varies_menu_and_fruit():
    snapshots = [
        _snapshot(1, date(2026, 7, 1), "Sate ayam", "Sate Ayam", "Jeruk Medan"),
        _snapshot(2, date(2026, 7, 2), "Ikan bumbu kuning", "Ikan Bumbu Kuning", "Pisang"),
        _snapshot(3, date(2026, 7, 3), "Tempe orek", "Tempe Orek", "Apel"),
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


def test_weekly_draft_never_repeats_a_menu_or_exceeds_the_combined_weekly_pagu():
    affordable_a = _snapshot(1, date(2026, 7, 1), "Sate ayam", "Sate Ayam", "Jeruk Medan")
    affordable_b = _snapshot(2, date(2026, 7, 2), "Ikan bumbu", "Ikan Bumbu", "Pisang")
    expensive = _snapshot(3, date(2026, 7, 3), "Daging premium", "Daging Premium", "Apel", price=50_000)
    result = _build_week_draft(
        site="MAJA", week_start=date(2026, 8, 3), days=3,
        snapshots=[affordable_a, affordable_b, expensive], target_pm=120,
        pagu_per_pm=None, knowledge=[], target_pm_breakdown={"small": 100, "large": 20},
        pagu_kecil=4_000, pagu_besar=4_000,
    )

    proposed = [day for day in result["days"] if day["state"] == "PROPOSED_DRAFT"]
    menu_keys = ["|".join(day["recipeNames"]).casefold() for day in proposed]
    assert len(proposed) == 3
    assert len(menu_keys) == len(set(menu_keys))
    assert any(day["withinPagu"] is False for day in proposed)
    assert result["summary"]["withinWeeklyPagu"] is True
    assert result["summary"]["totalEstimatedSpend"] <= result["summary"]["weeklyPaguTotal"]


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


def test_existing_day_uses_the_complete_daily_plan_not_a_single_fruit_fragment():
    fruit_fragment = {
        "id": "fruit-only", "distribution_date": date(2026, 8, 3),
        "payload": {"planName": "Jeruk Medan", "porsiKecil": 230, "porsiBesar": 107, "recipes": [{"name": "Jeruk Medan"}]},
        "items": [{"item_name": "Jeruk Medan", "category_code": "SAYUR_BUAH_BUMBU", "planned_qty": 60, "unit": "kg", "planning_price": 20_000}],
    }
    full_plan = _snapshot(9, date(2026, 8, 3), "Menu ayam lengkap", "Ayam Bumbu", "Pisang")
    full_plan["payload"]["porsiKecil"] = 1_043
    full_plan["payload"]["porsiBesar"] = 1_944
    full_plan["items"].append({"item_name": "Beras putih", "category_code": "BERAS", "planned_qty": 185, "unit": "kg", "planning_price": 14_900})

    result = _build_week_draft(
        site="MAJA", week_start=date(2026, 8, 3), days=1,
        snapshots=[fruit_fragment, full_plan], target_pm=120, pagu_per_pm=5000, knowledge=[],
    )

    assert result["days"][0]["state"] == "EXISTING"
    assert result["days"][0]["menuTitle"] == "Ayam Bumbu"
    assert len(result["days"][0]["materials"]) == 3


def test_menu_priority_uses_the_real_latest_use_not_the_oldest_duplicate():
    snapshots = [
        _snapshot(1, date(2026, 6, 1), "Sate ayam", "Sate Ayam", "Jeruk Medan"),
        _snapshot(2, date(2026, 8, 1), "Sate ayam", "Sate Ayam", "Jeruk Medan"),
        _snapshot(3, date(2026, 7, 1), "Ikan bumbu kuning", "Ikan Bumbu Kuning", "Pisang"),
    ]
    result = _build_week_draft(
        site="MAJA", week_start=date(2026, 8, 4), days=1, snapshots=snapshots,
        target_pm=120, pagu_per_pm=5000, knowledge=[],
    )
    # Ikan was last served on 1 July, while sate appeared again on 1 August.
    assert result["days"][0]["menuTitle"] == "Ikan bumbu kuning"
    assert result["days"][0]["sourceTemplate"]["daysSinceLastPlanned"] == 34


def test_egg_menu_is_only_scheduled_once_per_week_when_other_choices_exist():
    egg = _snapshot(1, date(2026, 7, 1), "Telur bumbu", "Telur Bumbu", "Jeruk Medan")
    egg["items"][0]["category_code"] = "TELUR"
    chicken = _snapshot(2, date(2026, 7, 2), "Ayam kecap", "Ayam Kecap", "Pisang")
    chicken["items"][0]["category_code"] = "AYAM"
    result = _build_week_draft(
        site="MAJA", week_start=date(2026, 8, 3), days=4, snapshots=[egg, chicken],
        target_pm=120, pagu_per_pm=5000, knowledge=[],
        target_pm_breakdown={"small": 100, "large": 20}, pagu_kecil=8000, pagu_besar=10000,
    )

    egg_days = [day for day in result["days"] if (day.get("menuProfile") or {}).get("isEggMenu")]
    assert len(egg_days) <= 1
    assert result["materialCatalog"]
