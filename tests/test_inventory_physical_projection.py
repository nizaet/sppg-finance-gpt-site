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
    assert row["planned_depletion"] == (5 if physical_check else 13)
    assert row["available_for_po"] == (2 if physical_check else 0)
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


def test_powder_cannot_inherit_fresh_garlic_master_by_substring():
    master = {"code": "FRESH", "canonical_name": "Bawang Putih", "normalized_canonical_name": "bawang putih", "aliases": [], "source_type": "INVENTORY_MASTER", "priority": 100}
    result = classify_item("Bawang Putih Bubuk", [master])
    assert result["canonicalItemName"] == "Bawang Putih Bubuk"
    assert result["inventoryItemCode"] is None
