from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.calculator_planning_bridge_api import _daily_plan_matches, _planning_payload


class _FakeFirestoreNode:
    def __init__(self, *, documents=None, failure=None, path=""):
        self.documents = documents or []
        self.failure = failure
        self.path = path
        self.document_ids = []
        self.where_args = None

    def collection(self, name):
        self.path = f"{self.path}/{name}".strip("/")
        return self

    def document(self, document_id):
        self.document_ids.append(document_id)
        self.id = document_id
        self.path = f"{self.path}/{document_id}".strip("/")
        return self

    def where(self, *args):
        self.where_args = args
        return self

    def limit(self, _value):
        return self

    def stream(self):
        if self.failure:
            raise self.failure
        return self.documents


def test_maja_august_25_reads_only_canonical_calculator_root(monkeypatch):
    plan = {
        "date": "2026-08-25",
        "planName": "MAJA 25 Agustus",
        "updatedAt": datetime(2026, 8, 21, tzinfo=timezone.utc),
        "shoppingListJSON": {"shoppingList": [{"item": "Beras", "jumlah": 100}]},
    }
    document = SimpleNamespace(id="maja-20260825", to_dict=lambda: plan)
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
