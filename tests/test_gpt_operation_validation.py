"""Malformed GPT commands must fail before any domain write, on preview and commit."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import gpt_operations_api as gateway


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(gateway.router)
    app.dependency_overrides[gateway.require_gpt_auth] = lambda: None
    write = Mock(side_effect=AssertionError("Unexpected settlement write"))
    monkeypatch.setattr(gateway, "create_settlement", write)
    with TestClient(app) as http:
        yield http, write


@pytest.mark.parametrize("commit", [False, True])
def test_dividend_advance_payload_returns_actionable_422_without_writes(client, commit):
    http, write = client
    response = http.post("/v1/gpt/operations/execute", json={
        "operation": "CREATE_SETTLEMENT", "commit": commit,
        "payload": {"site": "CEMPLANG", "vendor": "aya dev", "amount": 200000000,
                    "date": "2026-07-01", "transaction_ids": ["fixture-dividend"]},
    })
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["canCommit"] is False
    assert detail["committed"] is False
    assert "kasbon dividen" in detail["message"]
    assert any(error["loc"] == ["payload", "from_account_type"] for error in detail["errors"])
    assert "fixture-dividend" not in response.text
    write.assert_not_called()


@pytest.mark.parametrize("commit", [False, True])
def test_adding_an_account_does_not_silently_discard_debt_allocation(client, commit):
    http, write = client
    response = http.post("/v1/gpt/operations/execute", json={
        "operation": "CREATE_SETTLEMENT", "commit": commit,
        "payload": {"from_account_type": "YAYASAN", "amount": 200000000,
                    "vendor_code": "aya dev", "allocations": [{"amount": 200000000}]},
    })
    assert response.status_code == 422
    assert any(e["type"] == "extra_forbidden" for e in response.json()["detail"]["errors"])
    write.assert_not_called()


def test_valid_transfer_preview_keeps_date_and_explains_scope(client):
    http, write = client
    response = http.post("/v1/gpt/operations/execute", json={
        "operation": "CREATE_SETTLEMENT", "commit": False,
        "payload": {"from_account_type": "YAYASAN", "amount": 100000,
                    "settled_at": "2026-07-01T09:00:00+07:00"},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["canCommit"] is True
    assert body["committed"] is False
    assert body["normalizedPayload"]["settled_at"] == "2026-07-01T09:00:00+07:00"
    assert body["normalizedPayload"]["to_account_type"] == "BCA_OPERATIONAL"
    assert "tidak mengurangi hutang" in body["message"]
    write.assert_not_called()


def test_valid_transfer_commit_still_dispatches_once(client):
    http, write = client
    write.side_effect = None
    write.return_value = {"settlementId": 123, "classification": "INTER_ACCOUNT_SETTLEMENT"}
    response = http.post("/v1/gpt/operations/execute", json={
        "operation": "CREATE_SETTLEMENT", "commit": True,
        "payload": {"from_account_type": "KOPERASI", "amount": 100000},
    })
    assert response.status_code == 200
    assert response.json()["committed"] is True
    write.assert_called_once()
    assert write.call_args.args[0].amount == 100000


@pytest.mark.parametrize("amount", [0, -1, "NaN", "Infinity"])
def test_invalid_transfer_amounts_cannot_commit(client, amount):
    http, write = client
    response = http.post("/v1/gpt/operations/execute", json={
        "operation": "CREATE_SETTLEMENT", "commit": True,
        "payload": {"from_account_type": "YAYASAN", "amount": amount},
    })
    assert response.status_code == 422
    write.assert_not_called()


def test_other_operation_validation_also_returns_422_before_dispatch(client, monkeypatch):
    http, _ = client
    revise = Mock(side_effect=AssertionError("Unexpected PO write"))
    monkeypatch.setattr(gateway, "revise_purchase_order", revise)
    response = http.post("/v1/gpt/operations/execute", json={
        "operation": "REVISE_PURCHASE_ORDER", "commit": True,
        "payload": {"purchase_order_id": 0},
    })
    assert response.status_code == 422
    assert response.json()["detail"]["canCommit"] is False
    revise.assert_not_called()
