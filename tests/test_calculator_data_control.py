from backend.calculator_data_api import (
    PlanPreviewItem,
    _plan_preview_rows,
    _record_key,
    _same_content,
    router,
)


def test_calculator_data_router_is_mounted_under_v1_exactly_once():
    paths = {route.path for route in router.routes}
    assert router.prefix == ""
    assert "/calculator-data/plan-preview" in paths
    assert "/calculator-data/import" in paths
    assert not any(path.startswith("/v1/") for path in paths)


def test_master_record_keys_preserve_calculator_contracts():
    assert _record_key("PRICES", {"name": " Tepung Tapioka "}, "0") == "tepung tapioka"
    assert _record_key("GRAMASI", {"id": "ayam", "name": "Ayam"}, "0") == "ayam"
    assert _record_key("RECIPES", {"id": "ayam_kecap", "name": "Ayam Kecap"}, "0") == "ayam_kecap"


def test_content_compare_ignores_export_timestamps_and_ids():
    old = {"id": "r1", "name": "Sup", "updatedAt": "old", "ingredients": [{"name": "Wortel", "quantity_gr": 10}]}
    new = {"id": "r2", "name": "Sup", "updatedAt": {"seconds": 123}, "ingredients": [{"name": "Wortel", "quantity_gr": 10}]}
    assert _same_content(old, new)


def test_plan_preview_allows_distinct_plans_on_same_date_and_skips_exact_duplicates(monkeypatch):
    monkeypatch.setattr(
        "backend.calculator_data_api._existing_plan_dates",
        lambda site: {
            "2026-08-16": [{"documentId": "old", "planName": "Lama", "itemHash": "a" * 8}],
            "2026-08-17": [{"documentId": "regular", "planName": "Reguler", "itemHash": "z" * 8}],
        },
    )
    rows = _plan_preview_rows("MAJA", [
        PlanPreviewItem(client_key="0", date="2026-08-16", plan_name="Existing", item_hash="a" * 8),
        PlanPreviewItem(client_key="1", date="2026-08-17", plan_name="Menu Kering", item_hash="b" * 8),
        PlanPreviewItem(client_key="2", date="2026-08-17", plan_name="Menu Tambahan", item_hash="c" * 8),
        PlanPreviewItem(client_key="3", date="2026-08-18", plan_name="New", item_hash="d" * 8),
        PlanPreviewItem(client_key="4", date="2026-08-18", plan_name="New duplicate", item_hash="d" * 8),
    ])
    assert rows[0]["status"] == "ALREADY_EXISTS" and rows[0]["selectable"] is False
    assert rows[1]["status"] == "ADDITIONAL_PLAN_SAME_DATE" and rows[1]["defaultSelected"] is True
    assert rows[2]["status"] == "ADDITIONAL_PLAN_SAME_DATE" and rows[2]["defaultSelected"] is True
    assert rows[3]["status"] == "NEW" and rows[3]["defaultSelected"] is True
    assert rows[4]["status"] == "DUPLICATE_CONTENT_IN_FILE" and rows[4]["selectable"] is False
