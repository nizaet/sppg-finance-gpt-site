from __future__ import annotations

import pytest
from pydantic import ValidationError

from hermes_lab import runtime


def test_runtime_adds_only_read_context_and_receiving_preview_actions() -> None:
    schema = runtime.base._build_chatgpt_action_schema("https://hermes.example.test")
    paths = schema["paths"]

    assert "/v1/lab/context" in paths
    assert paths["/v1/lab/context"]["get"]["operationId"] == "readHermesSppgContext"
    assert "/v1/lab/receiving-preview" in paths
    assert paths["/v1/lab/receiving-preview"]["post"]["operationId"] == "previewHermesReceivingMultiPo"

    # Existing production-facing action contract remains present.
    assert "/v1/lab/purchase-orders" in paths
    assert "/v1/lab/proposals" in paths


def test_runtime_receiving_contract_has_no_commit_capability() -> None:
    with pytest.raises(ValidationError):
        runtime.LabReceivingPreviewRequest(
            site="MAJA",
            vendor_code="HOLIL",
            text="Wortel 10 kg",
            commit=True,
        )


def test_runtime_policy_requires_multi_po_preview_for_receiving() -> None:
    policy = runtime.base.SYSTEM_POLICY.lower()
    assert "read-only receiving preview" in policy
    assert "multiple pos" in policy or "multiple pOs".lower() in policy
    assert "never claim that a preview was saved or committed" in policy
