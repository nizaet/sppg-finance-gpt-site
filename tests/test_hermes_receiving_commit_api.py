from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend import hermes_receiving_commit_api as commit_api
from backend import hermes_receiving_guard as guard


def test_confirmation_token_is_bound_to_exact_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPPG_HERMES_APPROVAL_KEY", "test-approval-key")
    payload = {"site": "MAJA", "text": "Wortel 10 kg", "vendor_code": "HOLIL"}
    token = guard.issue_receiving_confirmation_token(payload)

    guard.validate_receiving_confirmation_token(payload, token)

    changed = {**payload, "text": "Wortel 11 kg"}
    with pytest.raises(HTTPException, match="does not match payload"):
        guard.validate_receiving_confirmation_token(changed, token)


def test_over_receipt_is_not_commit_eligible() -> None:
    result = {
        "canCommit": True,
        "matches": [
            {"allocations": [{"allocated_qty": 11, "outstanding_before": 10, "over_receipt": True}]}
        ],
    }
    assert guard.receiving_commit_eligible(result) is False


def test_commit_rechecks_live_preview_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPPG_HERMES_APPROVAL_KEY", "test-approval-key")
    preview_payload = {"site": "MAJA", "text": "Wortel 10 kg", "vendor_code": "HOLIL"}
    token = guard.issue_receiving_confirmation_token(preview_payload)
    calls: list[bool] = []

    def fake_resolver(payload):
        calls.append(bool(payload.commit))
        if not payload.commit:
            return {
                "committed": False,
                "canCommit": True,
                "matches": [{"allocations": [{"over_receipt": False}]}],
                "purchaseOrderIds": [123],
                "poCodes": ["PO-MAJA-TEST"],
            }
        return {
            "committed": True,
            "receiptId": 456,
            "receiptIds": [456],
            "purchaseOrderIds": [123],
            "poCodes": ["PO-MAJA-TEST"],
            "stockCommitted": True,
        }

    monkeypatch.setattr(commit_api, "receive_from_whatsapp_v2", fake_resolver)
    request = commit_api.HermesReceivingCommitIn(
        site="MAJA",
        text="Wortel 10 kg",
        vendor_code="HOLIL",
        confirmation_token=token,
        confirmation="COMMIT TRUE",
    )

    result = commit_api.commit_hermes_receiving(request, _auth=None)
    assert calls == [False, True]
    assert result["committed"] is True
    assert result["operationalMutation"] is True
    assert result["humanConfirmation"] is True


def test_commit_blocks_when_live_preview_becomes_unsafe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPPG_HERMES_APPROVAL_KEY", "test-approval-key")
    preview_payload = {"site": "MAJA", "text": "Wortel 10 kg", "vendor_code": "HOLIL"}
    token = guard.issue_receiving_confirmation_token(preview_payload)

    def fake_resolver(payload):
        assert payload.commit is False
        return {
            "committed": False,
            "canCommit": True,
            "matches": [{"allocations": [{"over_receipt": True}]}],
        }

    monkeypatch.setattr(commit_api, "receive_from_whatsapp_v2", fake_resolver)
    request = commit_api.HermesReceivingCommitIn(
        site="MAJA",
        text="Wortel 10 kg",
        vendor_code="HOLIL",
        confirmation_token=token,
        confirmation="COMMIT TRUE",
    )

    with pytest.raises(HTTPException) as exc_info:
        commit_api.commit_hermes_receiving(request, _auth=None)
    assert exc_info.value.status_code == 409
