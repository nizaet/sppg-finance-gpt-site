from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.calculator_planning_bridge_api import (
    CalculatorPlanningSyncIn,
    _daily_plan_matches,
    _planning_payload,
    sync_calculator_planning,
)


class _FakeFirestoreQuery:
    def __init__(self, client, *, path="", group=False, where_args=None):
        self.client = client
        self.path = path
        self.group = group
        self.where_args = where_args

    @property
    def id(self):
        return self.path.rsplit("/", 1)[-1]

    def collection(self, name):
        return _FakeFirestoreQuery(self.client, path=f"{self.path}/{name}".strip("/"), group=self.group)

    def document(self, document_id):
        self.client.document_ids.append(document_id)
        return _FakeFirestoreQuery(self.client, path=f"{self.path}/{document_id}".strip("/"), group=self.group)

    def where(self, *args):
        self.client.where_args = args
        return _FakeFirestoreQuery(self.client, path=self.path, group=self.group, where_args=args)

    def limit(self, _value):
        return self

    def stream(self):
        if self.client.failure:
            raise self.client.failure
        if self.where_args and self.client.where_failure:
            raise self.client.where_failure
        documents = self.client.group_documents if self.group else self.client.documents
        if not self.where_args:
            return documents
        field, operator, wanted = self.where_args
        assert operator == "=="
        return [snap for snap in documents if (snap.to_dict() or {}).get(field) == wanted]


class _FakeFirestoreNode:
    def __init__(self, *, documents=None, group_documents=None, failure=None, where_failure=None, project="sppg-finance-gpt"):
        self.documents = documents or []
        self.group_documents = group_documents or []
        self.failure = failure
        self.where_failure = where_failure
        self.project = project
        self.document_ids = []
        self.where_args = None
        self.collection_group_calls = 0

    def collection(self, name):
        return _FakeFirestoreQuery(self, path=name)

    def collection_group(self, name):
        self.collection_group_calls += 1
        return _FakeFirestoreQuery(self, path=name, group=True)


def _snapshot(document_id, data, *, app_id="sppg-maja-gpt-site"):
    return SimpleNamespace(
        id=document_id,
        to_dict=lambda: data,
        reference=SimpleNamespace(path=f"artifacts/{app_id}/public/data/dailyPlans/{document_id}"),
    )


def test_maja_august_25_reads_only_canonical_calculator_root(monkeypatch):
    plan = {
        "date": "2026-08-25",
        "planName": "MAJA 25 Agustus",
        "updatedAt": datetime(2026, 8, 21, tzinfo=timezone.utc),
        "shoppingListJSON": {"shoppingList": [{"item": "Beras", "jumlah": 100}]},
    }
    document = _snapshot("maja-20260825", plan)
    firestore = _FakeFirestoreNode(documents=[document])
    monkeypatch.setenv("SPPG_MAJA_CALCULATOR_APP_ID", "wrong-deployment-override")
    monkeypatch.setattr("backend.calculator_planning_bridge_api.firestore_client", lambda _database: firestore)

    app_id, selected, data, candidates = _daily_plan_matches("MAJA", date(2026, 8, 25))

    assert app_id == "sppg-maja-gpt-site"
    assert selected.id == "maja-20260825"
    assert data["planName"] == "MAJA 25 Agustus"
    assert len(candidates) == 1
    assert "sppg-maja-gpt-site" in firestore.document_ids
    assert "wrong-deployment-override" not in firestore.document_ids
    assert firestore.where_args == ("date", "==", "2026-08-25")
    assert firestore.collection_group_calls == 0


def test_legacy_date_format_on_canonical_root_is_still_read(monkeypatch):
    plan = {
        "tanggal": "25/08/2026",
        "planName": "MAJA format lama",
        "shoppingListJSON": {"shoppingList": [{"item": "Beras", "jumlah": 100}]},
    }
    document = _snapshot("legacy-maja-20260825", plan)
    firestore = _FakeFirestoreNode(documents=[document])
    monkeypatch.setattr("backend.calculator_planning_bridge_api.firestore_client", lambda _database: firestore)

    app_id, selected, data, candidates = _daily_plan_matches("MAJA", date(2026, 8, 25))

    assert app_id == "sppg-maja-gpt-site"
    assert selected.id == "legacy-maja-20260825"
    assert data["tanggal"] == "25/08/2026"
    assert candidates[0]["normalized_date"] == "2026-08-25"
    assert firestore.collection_group_calls == 0


def test_invalid_indexed_query_falls_back_to_canonical_scan(monkeypatch):
    plan = {
        "date": "2026-08-26",
        "planName": "MAJA 26 Agustus",
        "shoppingListJSON": {"shoppingList": [{"item": "Beras", "jumlah": 100}]},
    }
    document = _snapshot("maja-20260826", plan)
    firestore = _FakeFirestoreNode(documents=[document], where_failure=ValueError("InvalidArgument"))
    monkeypatch.setattr("backend.calculator_planning_bridge_api.firestore_client", lambda _database: firestore)

    app_id, selected, data, candidates = _daily_plan_matches("MAJA", date(2026, 8, 26))

    assert app_id == "sppg-maja-gpt-site"
    assert selected.id == "maja-20260826"
    assert data["planName"] == "MAJA 26 Agustus"
    assert len(candidates) == 1
    assert firestore.collection_group_calls == 0


def test_accountant_table_prefers_maker_returned_by_accountant_flow():
    source = Path("src/operations/OperationsAccountantBgn.jsx").read_text(encoding="utf-8")
    assert "const existingMaker = x.maker_id" in source


def test_unique_legacy_app_root_is_discovered_without_crossing_sites(monkeypatch):
    plan = {
        "date": "2026-08-25",
        "planName": "MAJA dari root lama",
        "shoppingListJSON": {"shoppingList": [{"item": "Beras", "jumlah": 100}]},
    }
    document = _snapshot("maja-old-20260825", plan, app_id="legacy-maja-calculator")
    firestore = _FakeFirestoreNode(group_documents=[document])
    monkeypatch.setattr("backend.calculator_planning_bridge_api.firestore_client", lambda _database: firestore)

    app_id, selected, data, candidates = _daily_plan_matches("MAJA", date(2026, 8, 25))

    assert app_id == "legacy-maja-calculator"
    assert selected.id == "maja-old-20260825"
    assert data["planName"] == "MAJA dari root lama"
    assert {candidate["app_id"] for candidate in candidates} == {"legacy-maja-calculator"}
    assert firestore.collection_group_calls == 4


def test_other_site_root_is_never_used_as_fallback(monkeypatch):
    plan = {"date": "2026-08-25", "planName": "CEMPLANG", "shoppingListJSON": {"shoppingList": []}}
    document = _snapshot("cemplang-20260825", plan, app_id="sppg-cemplang2-gpt-site")
    firestore = _FakeFirestoreNode(group_documents=[document])
    monkeypatch.setattr("backend.calculator_planning_bridge_api.firestore_client", lambda _database: firestore)

    with pytest.raises(HTTPException) as raised:
        _daily_plan_matches("MAJA", date(2026, 8, 25))

    assert raised.value.status_code == 404
    assert raised.value.detail["canonicalAppId"] == "sppg-maja-gpt-site"
    assert raised.value.detail["projectId"] == "sppg-finance-gpt"


def test_multiple_legacy_roots_stop_before_guessing(monkeypatch):
    plan = {"date": "2026-08-25", "shoppingListJSON": {"shoppingList": []}}
    firestore = _FakeFirestoreNode(group_documents=[
        _snapshot("one", {**plan, "planName": "Root satu"}, app_id="maja-old-one"),
        _snapshot("two", {**plan, "planName": "Root dua"}, app_id="maja-old-two"),
    ])
    monkeypatch.setattr("backend.calculator_planning_bridge_api.firestore_client", lambda _database: firestore)

    with pytest.raises(HTTPException) as raised:
        _daily_plan_matches("MAJA", date(2026, 8, 25))

    assert raised.value.status_code == 409
    assert raised.value.detail["candidateAppIds"] == ["maja-old-one", "maja-old-two"]


def test_firestore_failure_is_not_reported_as_plan_not_found(monkeypatch):
    firestore = _FakeFirestoreNode(failure=PermissionError("denied"))
    monkeypatch.setattr("backend.calculator_planning_bridge_api.firestore_client", lambda _database: firestore)

    with pytest.raises(HTTPException) as raised:
        _daily_plan_matches("CEMPLANG", date(2026, 8, 25))

    assert raised.value.status_code == 502
    assert raised.value.detail["message"] == "gagal membaca rencana Kalkulator dari Firestore"
    assert raised.value.detail["appId"] == "sppg-cemplang2-gpt-site"
    assert raised.value.detail["errorType"] == "PermissionError"


def test_po_planner_syncs_before_starting_stock_projection():
    source = Path("src/operations/OperationsPoPlanner.jsx").read_text(encoding="utf-8")
    start = source.index("  const pullDailyData = async () => {")
    end = source.index("\n  const clearDailyPulledData", start)
    pull_daily = source[start:end]

    sync_index = pull_daily.index("operationsApi.syncCalculatorPlanning")
    stock_index = pull_daily.index("operationsApi.getInventoryBalances")
    assert sync_index < stock_index
    assert "operationsApi.getPlanningSnapshots" not in pull_daily
    assert "operationsApi.getPlanningSnapshot" not in pull_daily
    assert "Gagal menyinkronkan planning Kalkulator" in pull_daily
    assert "Planning ditemukan, tetapi jadwal atau stok gagal ditarik" in pull_daily


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


def test_explicit_reminder_sync_retires_stale_snapshot_when_source_plan_was_deleted(monkeypatch):
    missing = HTTPException(404, detail={"message": "not found"})
    monkeypatch.setattr("backend.calculator_planning_bridge_api._planning_payload", lambda *_: (_ for _ in ()).throw(missing))
    monkeypatch.setattr("backend.calculator_planning_bridge_api.database_ready", lambda: True)

    class _Cursor:
        def execute(self, sql, params):
            assert "source_system='CALCULATOR_FIRESTORE'" in sql
            assert params == ("MAJA", date(2026, 8, 28))

        def fetchall(self):
            return [{"id": 91}]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Connection:
        committed = False

        def cursor(self):
            return _Cursor()

        def commit(self):
            self.committed = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_connection = _Connection()
    monkeypatch.setattr("backend.calculator_planning_bridge_api.connection", lambda: fake_connection)

    result = sync_calculator_planning(CalculatorPlanningSyncIn(
        site="MAJA",
        distribution_date=date(2026, 8, 28),
        deactivate_missing=True,
    ))

    assert result["sourceMissing"] is True
    assert result["supersededSnapshotIds"] == [91]
    assert result["itemCount"] == 0
    assert fake_connection.committed is True
