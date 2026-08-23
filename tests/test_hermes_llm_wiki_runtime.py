from __future__ import annotations

import pytest
from pydantic import ValidationError

from hermes_lab import runtime


def test_runtime_adds_context_knowledge_receiving_preview_and_commit_actions() -> None:
    schema = runtime.base._build_chatgpt_action_schema("https://hermes.example.test")
    paths = schema["paths"]

    assert "/v1/lab/context" in paths
    assert paths["/v1/lab/context"]["get"]["operationId"] == "readHermesSppgContext"
    assert "/v1/lab/knowledge" in paths
    assert paths["/v1/lab/knowledge"]["post"]["operationId"] == "storeHermesKnowledge"
    assert "/v1/lab/receiving-preview" in paths
    assert paths["/v1/lab/receiving-preview"]["post"]["operationId"] == "previewHermesReceivingMultiPo"
    assert "/v1/lab/receiving-commit" in paths
    assert paths["/v1/lab/receiving-commit"]["post"]["operationId"] == "commitHermesReceiving"

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


def test_runtime_receiving_preview_contract_has_no_commit_field() -> None:
    with pytest.raises(ValidationError):
        runtime.LabReceivingPreviewRequest(
            site="MAJA",
            vendor_code="HOLIL",
            text="Wortel 10 kg",
            commit=True,
        )


def test_runtime_receiving_commit_requires_exact_human_confirmation() -> None:
    base = {
        "site": "MAJA",
        "vendor_code": "HOLIL",
        "text": "Wortel 10 kg",
        "confirmation_token": "1." + "a" * 64,
    }
    with pytest.raises(ValidationError):
        runtime.LabReceivingCommitRequest(**base, confirmation="YA")

    request = runtime.LabReceivingCommitRequest(**base, confirmation="COMMIT TRUE")
    assert request.confirmation == "COMMIT TRUE"


def test_runtime_policy_requires_preview_then_explicit_commit_true() -> None:
    policy = runtime.base.SYSTEM_POLICY.lower()
    assert "previewhermesreceivingmultipo" in policy
    assert "commiteligible=true" in policy
    assert "confirmationtoken" in policy
    assert "commit true" in policy
    assert "never call receiving commit proactively" in policy
