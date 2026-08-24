from datetime import date

from fastapi import HTTPException

from backend import operational_search_api as search_api


class _Cursor:
    def __init__(self, captured):
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.captured.append((sql, list(params)))

    @staticmethod
    def fetchall():
        return []


class _Connection:
    def __init__(self, captured):
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _Cursor(self.captured)


def test_purchase_order_search_filters_inclusive_distribution_date_range(monkeypatch):
    captured = []
    monkeypatch.setattr(search_api, "database_ready", lambda: True)
    monkeypatch.setattr(search_api, "connection", lambda: _Connection(captured))

    result = search_api.search_purchase_orders(
        site="MAJA",
        vendor="WIKIAN",
        distribution_date=None,
        date_from=date(2026, 8, 23),
        date_to=date(2026, 8, 26),
        status="",
        limit=50,
    )

    sql, params = captured[0]
    assert "pc.distribution_date>=%s" in sql
    assert "pc.distribution_date<=%s" in sql
    assert params == ["MAJA", "WIKIAN", date(2026, 8, 23), date(2026, 8, 26), 50]
    assert result == {"items": [], "count": 0}


def test_purchase_order_search_rejects_reversed_date_range(monkeypatch):
    monkeypatch.setattr(search_api, "database_ready", lambda: True)

    try:
        search_api.search_purchase_orders(
            site="MAJA",
            vendor="WIKIAN",
            distribution_date=None,
            date_from=date(2026, 8, 26),
            date_to=date(2026, 8, 23),
            status="",
            limit=50,
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail == "dateFrom must be on or before dateTo"
    else:
        raise AssertionError("reversed date range should be rejected")
