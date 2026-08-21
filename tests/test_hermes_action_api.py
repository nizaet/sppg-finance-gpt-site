import inspect

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

import backend.hermes_action_api as hermes_action_api


def _proposal(**overrides):
    values = {
        "source_ref": "hermes:test:001",
        "action_type": "CREATE_PO",
        "site": "CEMPLANG",
        "vendor_code": "HOLIL",
        "target_type": "purchase_order",
        "rationale": "Operator asked Hermes to prepare a PO proposal.",
        "confidence": 0.9,
        "payload": {"distributionDate": "2026-08-22"},
    }
    values.update(overrides)
    return hermes_action_api.HermesActionProposalIn(**values)


def test_proposal_keys_are_stable_and_payload_sensitive():
    first = hermes_action_api.proposal_keys(_proposal())
    replay = hermes_action_api.proposal_keys(_proposal())
    changed = hermes_action_api.proposal_keys(
        _proposal(payload={"distributionDate": "2026-08-23"})
    )

    assert first == replay
    assert first != changed
    assert first[0].startswith("hermes-proposal:")
    assert first[1].startswith("hermes-action:")


def test_action_type_is_strictly_allowlisted():
    with pytest.raises(ValidationError):
        _proposal(action_type="DELETE_DATABASE")


def test_approval_requires_separate_key(monkeypatch):
    monkeypatch.setenv("SPPG_HERMES_APPROVAL_KEY", "approval-secret")

    with pytest.raises(HTTPException) as exc:
        hermes_action_api.require_hermes_approval_auth(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="gpt-or-hermes-key")
        )
    assert exc.value.status_code == 403

    hermes_action_api.require_hermes_approval_auth(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="approval-secret")
    )


def test_hermes_cannot_be_named_as_approver():
    with pytest.raises(ValidationError):
        hermes_action_api.HermesActionDecisionIn(
            decision="APPROVE",
            actor="hermes-agent",
        )


def test_router_has_no_execute_endpoint_or_operational_insert():
    paths = {route.path for route in hermes_action_api.router.routes}
    assert "/gpt/hermes-actions/proposals" in paths
    assert "/gpt/hermes-actions/proposals/{action_id}/decision" in paths
    assert all("execute" not in path.lower() for path in paths)

    source = inspect.getsource(hermes_action_api).lower()
    forbidden_writes = (
        "insert into purchase_orders",
        "insert into goods_receipts",
        "insert into vendor_payments",
        "insert into finance_transactions",
        "insert into inventory_ledger",
    )
    assert all(statement not in source for statement in forbidden_writes)
