from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest

from backend import inventory_projection_v2_api as projection
from backend import inventory_summary_api as summary
from backend.inventory_api import classify_item


class Cursor:
    def __init__(self, results):
        self.results = iter(results)

    def execute(self, sql, params=None):
        self.rows = next(self.results)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def connection_for(results):
    cur = Cursor(results)
    class Connection:
        def cursor(self):
            return cur
    @contextmanager
    def connect():
        yield Connection()
    return connect


@pytest.mark.parametrize("site", ["MAJA", "CEMPLANG"])
@pytest.mark.parametrize("physical_check", [False, True])
def test_corrections_replace_old_plan_estimates_but_keep_later_cooking(site, physical_check, monkeypatch):
    checked = datetime(2026, 9, 11, 18, tzinfo=timezone.utc) if physical_check else None  # Sept 12 Jakarta
    base = {"latestStockOpnameDate": date(2026, 9, 4), "forDate": date(2026, 9, 14), "items": [{
        "item_name": "bawang bombay", "unit": "kg", "so_qty": 1.98, "movement_delta": 5.02,
        "actual_usage_depletion": 0, "last_stock_check_at": checked,
    }]}
    monkeypatch.setattr(projection, "inventory_balances", lambda **kwargs: base)
    monkeypatch.setattr(projection, "load_item_matchers", lambda *args: [])
    plans = [
        {"item_name": "Bawang Bombay", "unit": "kg", "planned_qty": 8, "distribution_date": date(2026, 9, 10)},
        {"item_name": "Bombay", "unit": "kg", "planned_qty": 2, "distribution_date": date(2026, 9, 12)},
        {"item_name": "Bawang Bombay", "unit": "kg", "planned_qty": 3, "distribution_date": date(2026, 9, 13)},
    ]
    monkeypatch.setattr(projection, "connection", connection_for([[], [], plans, []]))
    result = projection.inventory_balances_v2(site=site, limit=1000, for_date=date(2026, 9, 14))
    row = result["items"][0]
    assert row["actual_balance"] == 7
    # The 13 Sept cooking plan is the target that its PO fulfils, not a prior
    # depletion. Only 10 and 12 Sept can consume stock first.
    assert row["planned_depletion"] == (0 if physical_check else 10)
    assert row["available_for_po"] == (7 if physical_check else 0)
    assert row["stock_type_code"] == "BAWANG_BOMBAY"


@pytest.mark.parametrize("source_type", ["MANUAL_STOCK_EDIT", "GOODS_RECEIPT"])
def test_only_explicit_physical_recount_creates_new_estimate_anchor(source_type, monkeypatch):
    checked = datetime(2026, 9, 11, 18, tzinfo=timezone.utc)
    so = {"id": 57, "stock_date": date(2026, 9, 4), "created_at": datetime(2026, 9, 4, tzinfo=timezone.utc)}
    items = [{"area_code": None, "raw_item_name": "Bawang Bombay", "canonical_item_name": "Bawang Bombay", "inventory_item_code": None, "qty": 1.98, "unit": "kg"}]
    movements = [{"item_name": "Bawang Bombay", "qty": 5.02, "unit": "kg", "from_location": "MANUAL_ADJUSTMENT", "to_location": "CEMPLANG", "movement_type": "MANUAL_ADJUSTMENT", "source_type": source_type, "notes": '{"target_balance":7}', "occurred_at": checked}]
    plans = [{"item_name": "Bawang Bombay", "unit": "kg", "planned_qty": 8, "distribution_date": date(2026, 9, 10)}]
    monkeypatch.setattr(summary, "require_db", lambda: None)
    monkeypatch.setattr(summary, "load_item_matchers", lambda *args: [])
    monkeypatch.setattr(summary, "connection", connection_for([[so], [so], items, movements, [], plans]))
    row = summary.inventory_balances(site="CEMPLANG", limit=1000, for_date=date(2026, 9, 14), include_current_corrections=True)["items"][0]
    assert row["actual_balance"] == 7
    assert row["last_stock_check_at"] == (checked if source_type == "MANUAL_STOCK_EDIT" else None)
    assert row["planned_depletion"] == (0 if source_type == "MANUAL_STOCK_EDIT" else 8)


def test_late_same_day_receipt_does_not_resurrect_stock_after_so(monkeypatch):
    so = {"id": 60, "stock_date": date(2026, 9, 16), "created_at": datetime(2026, 9, 16, 1, tzinfo=timezone.utc)}
    items = [{"area_code": None, "raw_item_name": "Knorr Chicken Powder", "canonical_item_name": "Knorr Chicken Powder", "inventory_item_code": None, "qty": 0, "unit": "kg"}]
    late_receipt = [{"item_name": "Knorr Chicken Powder", "qty": 2, "unit": "kg", "from_location": "KOPERASI", "to_location": "CEMPLANG", "movement_type": "KOPERASI_STOCK_TRANSFER", "source_type": "GOODS_RECEIPT", "notes": None, "occurred_at": datetime(2026, 9, 16, 5, tzinfo=timezone.utc)}]
    monkeypatch.setattr(summary, "require_db", lambda: None)
    monkeypatch.setattr(summary, "load_item_matchers", lambda *args: [])
    monkeypatch.setattr(summary, "connection", connection_for([[so], [so], items, late_receipt, [], []]))
    result = summary.inventory_balances(site="CEMPLANG", limit=1000, for_date=date(2026, 9, 17))
    assert result["items"][0]["actual_balance"] == 0


def test_same_day_manual_added_stock_is_visible_after_so(monkeypatch):
    so = {"id": 61, "stock_date": date(2026, 9, 16), "created_at": datetime(2026, 9, 16, 1, tzinfo=timezone.utc)}
    items = [{"area_code": None, "raw_item_name": "Minyak Goreng", "canonical_item_name": "Minyak Goreng", "inventory_item_code": None, "qty": 0, "unit": "liter"}]
    adjustment = [{"item_name": "Minyak Goreng", "qty": 5, "unit": "liter", "from_location": "MANUAL_ADJUSTMENT", "to_location": "CEMPLANG", "movement_type": "MANUAL_ADJUSTMENT", "source_type": "MANUAL_STOCK_EDIT", "notes": '{"target_balance":5}', "occurred_at": datetime(2026, 9, 16, 8, tzinfo=timezone.utc)}]
    monkeypatch.setattr(summary, "require_db", lambda: None)
    monkeypatch.setattr(summary, "load_item_matchers", lambda *args: [])
    monkeypatch.setattr(summary, "connection", connection_for([[so], [so], items, adjustment, [], []]))
    result = summary.inventory_balances(site="CEMPLANG", limit=1000, for_date=date(2026, 9, 17))
    assert result["items"][0]["actual_balance"] == 5


def test_same_day_po_stock_confirmation_is_visible_after_so(monkeypatch):
    so = {"id": 62, "stock_date": date(2026, 9, 16), "created_at": datetime(2026, 9, 16, 1, tzinfo=timezone.utc)}
    items = [{"area_code": None, "raw_item_name": "Bawang Bombay", "canonical_item_name": "Bawang Bombay", "inventory_item_code": None, "qty": 6.35, "unit": "kg"}]
    correction = [{"item_name": "Bawang Bombay", "qty": 5, "unit": "kg", "from_location": "MAJA", "to_location": "MANUAL_CORRECTION", "movement_type": "MANUAL_STOCK_CORRECTION", "source_type": "MANUAL_STOCK_EDIT", "notes": '{"source":"PO_REMINDER_STOCK_CONFIRMATION","target_balance":1.35}', "occurred_at": datetime(2026, 9, 16, 8, tzinfo=timezone.utc)}]
    monkeypatch.setattr(summary, "require_db", lambda: None)
    monkeypatch.setattr(summary, "load_item_matchers", lambda *args: [])
    monkeypatch.setattr(summary, "connection", connection_for([[so], [so], items, correction, [], []]))
    result = summary.inventory_balances(site="MAJA", limit=1000, for_date=date(2026, 9, 17))
    assert result["items"][0]["actual_balance"] == 1.35
    assert result["items"][0]["last_stock_check_at"] == datetime(2026, 9, 16, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize("site", ["MAJA", "CEMPLANG"])
def test_po_target_cooking_is_not_deducted_before_its_own_po(site, monkeypatch):
    checked = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)  # Sept 16 Jakarta
    base = {"latestStockOpnameDate": date(2026, 9, 16), "forDate": date(2026, 9, 18), "items": [{
        "item_name": "Garam", "unit": "kg", "so_qty": 0,
        "movement_delta": 8, "actual_usage_depletion": 0, "last_stock_check_at": checked,
    }]}
    monkeypatch.setattr(projection, "inventory_balances", lambda **kwargs: base)
    monkeypatch.setattr(projection, "load_item_matchers", lambda *args: [])
    plans = [
        {
            "item_name": "Garam", "unit": "kg", "planned_qty": 5,
            "cooking_date": date(2026, 9, 16), "distribution_date": date(2026, 9, 17),
        },
        {
            "item_name": "Garam", "unit": "kg", "planned_qty": 3,
            "cooking_date": date(2026, 9, 17), "distribution_date": date(2026, 9, 18),
        },
    ]
    monkeypatch.setattr(projection, "connection", connection_for([[], [], plans, []]))

    row = projection.inventory_balances_v2(site=site, limit=1000, for_date=date(2026, 9, 18))["items"][0]

    assert row["actual_balance"] == 8
    assert row["planned_depletion"] == 0
    assert row["available_for_po"] == 8


@pytest.mark.parametrize("site", ["MAJA", "CEMPLANG"])
def test_same_day_so_is_not_depleted_again_by_same_day_plan(site, monkeypatch):
    base = {"latestStockOpnameDate": date(2026, 9, 14), "forDate": date(2026, 9, 15), "items": [{
        "item_name": "Lada Putih", "unit": "kg", "so_qty": 1,
        "movement_delta": 0, "actual_usage_depletion": 0, "last_stock_check_at": None,
    }]}
    monkeypatch.setattr(projection, "inventory_balances", lambda **kwargs: base)
    monkeypatch.setattr(projection, "load_item_matchers", lambda *args: [])
    same_day_plan = [{
        "item_name": "Lada Putih Ladaku", "unit": "kg", "planned_qty": 1,
        "distribution_date": date(2026, 9, 14),
    }]
    monkeypatch.setattr(projection, "connection", connection_for([[], [], same_day_plan, []]))
    result = projection.inventory_balances_v2(site=site, limit=1000, for_date=date(2026, 9, 15))
    row = result["items"][0]
    assert row["actual_balance"] == 1
    assert row["planned_depletion"] == 0
    assert row["available_for_po"] == 1


def test_powder_cannot_inherit_fresh_garlic_master_by_substring():
    master = {"code": "FRESH", "canonical_name": "Bawang Putih", "normalized_canonical_name": "bawang putih", "aliases": [], "source_type": "INVENTORY_MASTER", "priority": 100}
    result = classify_item("Bawang Putih Bubuk", [master])
    assert result["canonicalItemName"] == "Bawang Putih Bubuk"
    assert result["inventoryItemCode"] is None


@pytest.mark.parametrize("site", ["MAJA", "CEMPLANG"])
def test_so_closes_previous_cooking_day_before_same_day_po(site, monkeypatch):
    # SO on Sept 23 is the physical result after Sept 23 cooking. When
    # drafting a PO for Sept 24 cooking, the prior 20 L plan must not be
    # deducted again: 36 L on hand against 50 L needed => order 14 L.
    base = {"latestStockOpnameDate": date(2026, 9, 23), "forDate": date(2026, 9, 25), "items": [{
        "item_name": "Minyak Goreng", "unit": "liter", "so_qty": 36,
        "movement_delta": 0, "actual_usage_depletion": 0, "last_stock_check_at": None,
    }]}
    monkeypatch.setattr(projection, "inventory_balances", lambda **kwargs: base)
    monkeypatch.setattr(projection, "load_item_matchers", lambda *args: [])
    plans = [
        {"item_name": "Minyak Goreng", "unit": "liter", "planned_qty": 20,
         "cooking_date": date(2026, 9, 23), "distribution_date": date(2026, 9, 24)},
        {"item_name": "Minyak Goreng", "unit": "liter", "planned_qty": 50,
         "cooking_date": date(2026, 9, 24), "distribution_date": date(2026, 9, 25)},
    ]
    monkeypatch.setattr(projection, "connection", connection_for([[], [], plans, []]))
    row = projection.inventory_balances_v2(site=site, limit=1000, for_date=date(2026, 9, 25), cooking_date=date(2026, 9, 24))["items"][0]
    assert row["actual_balance"] == 36
    assert row["planned_depletion"] == 0
    assert row["available_for_po"] == 36
