from __future__ import annotations

from copy import deepcopy
from typing import Any

from hermes_lab import app as base
from hermes_lab import runtime as runtime


app = runtime.app
app.version = "0.5.7"
_original_builder = base._build_chatgpt_action_schema


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root_probe() -> dict[str, Any]:
    """Return 200 for origin probes without exposing operational data."""
    return {
        "ok": True,
        "service": "sppg-hermes-lab",
        "version": app.version,
    }


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _success_schema_for(path: str) -> dict[str, Any]:
    """Small explicit response contracts for Custom GPT Actions.

    Keep response schemas primitive and predictable. Runtime responses may carry
    additional fields, but the Action schema advertises only the stable subset
    GPT needs to decide what happened.
    """

    if path == "/v1/lab/knowledge":
        return _object(
            {
                "stored": {"type": "boolean"},
                "databaseReady": {"type": "boolean"},
                "eventId": {"type": "integer"},
                "sourceKey": {"type": "string"},
                "knowledgeWrite": {"type": "boolean"},
                "knowledgeStatus": {"type": "string"},
                "operationalMutation": {"type": "boolean"},
            },
            ["stored", "knowledgeWrite", "operationalMutation"],
        )

    if path == "/v1/lab/purchase-orders":
        item = _object(
            {
                "purchase_order_id": {"type": "integer"},
                "po_code": {"type": "string"},
                "site": {"type": "string"},
                "vendor_code": {"type": "string"},
                "status": {"type": "string"},
                "distribution_date": {"type": "string"},
                "item_count": {"type": "integer"},
            },
            ["purchase_order_id", "po_code"],
        )
        return _object(
            {
                "items": {"type": "array", "items": item},
                "count": {"type": "integer"},
                "readOnly": {"type": "boolean"},
                "sourceOfTruth": {"type": "string"},
            },
            ["items", "count", "readOnly"],
        )

    if path == "/v1/lab/receiving-preview":
        return _object(
            {
                "committed": {"type": "boolean"},
                "canCommit": {"type": "boolean"},
                "commitEligible": {"type": "boolean"},
                "site": {"type": "string"},
                "multiPo": {"type": "boolean"},
                "poMatchConfidence": {"type": "number"},
                "requiresConfirmation": {"type": "boolean"},
                "readOnly": {"type": "boolean"},
                "operationalMutation": {"type": "boolean"},
                "sourceOfTruth": {"type": "string"},
                "confirmationExpiresInSeconds": {"type": "integer"},
                "commitBlockReason": {"type": "string"},
            },
            ["committed", "canCommit", "commitEligible", "site", "readOnly", "operationalMutation"],
        )

    if path == "/v1/lab/receiving-commit":
        return _object(
            {
                "committed": {"type": "boolean"},
                "operationalMutation": {"type": "boolean"},
                "mutationType": {"type": "string"},
                "humanConfirmation": {"type": "boolean"},
                "confirmation": {"type": "string"},
                "receiptId": {"type": "integer"},
                "stockCommitted": {"type": "boolean"},
                "stockInserted": {"type": "integer"},
                "stockDuplicates": {"type": "integer"},
            },
            ["committed", "operationalMutation", "humanConfirmation"],
        )

    if path == "/v1/lab/context":
        return _object(
            {
                "databaseReady": {"type": "boolean"},
                "readOnly": {"type": "boolean"},
                "sourceOfTruth": {"type": "string"},
                "accessMode": {"type": "string"},
                "topic": {"type": "string"},
            },
            ["readOnly", "sourceOfTruth"],
        )

    if path == "/v1/lab/proposals":
        return _object(
            {
                "proposalId": {"type": "integer"},
                "actionId": {"type": "integer"},
                "candidateStatus": {"type": "string"},
                "actionStatus": {"type": "string"},
                "inserted": {"type": "boolean"},
                "approvalRequired": {"type": "boolean"},
                "executed": {"type": "boolean"},
                "executionLocked": {"type": "boolean"},
            },
            ["proposalId", "actionId", "approvalRequired", "executed"],
        )

    if path == "/v1/lab/chat":
        return _object(
            {
                "answer": {"type": "string"},
                "mode": {"type": "string"},
                "model": {"type": "string"},
                "memory_loaded": {"type": "boolean"},
                "memory_stored": {"type": "boolean"},
            },
            ["answer", "mode", "model"],
        )

    return _object({"ok": {"type": "boolean"}})


def _replace_success_response_schema(path: str, operation: dict[str, Any]) -> None:
    responses = operation.setdefault("responses", {})
    for code, response in list(responses.items()):
        if not str(code).startswith("2") or not isinstance(response, dict):
            continue
        content = response.setdefault("content", {})
        app_json = content.setdefault("application/json", {})
        app_json["schema"] = _success_schema_for(path)


def build_chatgpt_action_schema_compat(public_origin: str) -> dict[str, Any]:
    """Keep request schemas strict and advertise small explicit success schemas."""

    schema = deepcopy(_original_builder(public_origin))
    schema.setdefault("info", {})["version"] = app.version
    for path, methods in schema.get("paths", {}).items():
        if path == "/health" or not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if isinstance(operation, dict):
                _replace_success_response_schema(path, operation)
    return schema


# The already-registered schema route resolves this module attribute at request
# time, so replacing it here changes only the generated Custom GPT schema.
base._build_chatgpt_action_schema = build_chatgpt_action_schema_compat
