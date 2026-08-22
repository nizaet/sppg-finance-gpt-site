from __future__ import annotations

import pytest
from pydantic import ValidationError

from hermes_lab import runtime


def test_runtime_adds_context_knowledge_and_receiving_preview_actions() -> None:
    schema = runtime.base._build_chatgpt_action_schema("https://hermes.example.test")
    paths = schema["paths"]

    assert "/v1/lab/context" in paths
    assert paths["/v1/lab/context"]["get"]["operationId"] == "readHermesSppgContext"
    assert "/v1/lab/knowledge" in paths
    assert paths["/v1/lab/knowledge"]["post"]["operationId"] == "storeHermesKnowledge"
    assert "/v1/lab/receiving-preview" in paths
    assert paths["/v1/lab/receiving-preview"]["post"]["operationId"] == "previewHermesReceivingMultiPo"

    # Existing production-facing action contract remains present.
    assert "/v1/lab/purchase-orders" in paths
    assert "/v1/lab/proposals" in paths


def test_runtime_knowledge_requires_explicit_facts() -> None:
    with pytest.raises(ValidationError):
        runtime.LabKnowledgeRequest(
            source_ref="test-empty",
            user_message="catat ini",
            facts=[],
        )


def test_runtime_policy_stores_only_explicit_user_knowledge() -> None:
    policy = runtime.base.SYSTEM_POLICY.lower()
    assert "storehermesknowledge" in policy
    assert "explicitly" in policy
    assert "do not promote assistant inference" in policy


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
    assert "multiple pos" in policy
    assert "never claim that a preview was saved or committed" in policy
