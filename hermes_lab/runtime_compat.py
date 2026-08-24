from __future__ import annotations

from typing import Any

from hermes_lab import app as base
from hermes_lab import runtime as runtime


app = runtime.app
app.version = "0.5.9"


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root_probe() -> dict[str, Any]:
    """Return 200 for origin probes without exposing operational data."""
    return {
        "ok": True,
        "service": "sppg-hermes-lab",
        "version": app.version,
    }


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _json_response(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": "Successful Response",
        "content": {"application/json": {"schema": schema}},
    }


def _query(name: str, schema: dict[str, Any], *, required: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "in": "query",
        "required": required,
        "schema": schema,
    }


def _body(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "required": True,
        "content": {"application/json": {"schema": schema}},
    }


def build_chatgpt_action_schema_static(public_origin: str) -> dict[str, Any]:
    """Return a small hand-written OpenAPI contract for Custom GPT Actions.

    This deliberately avoids FastAPI-generated components, $ref, nullable unions,
    Any-heavy schemas, and nested Pydantic response models. Runtime routes and
    payload validation remain unchanged; only the GPT-facing contract is static.
    """

    health_response = _object(
        {
            "ok": {"type": "boolean"},
            "service": {"type": "string"},
            "mode": {"type": "string"},
            "hermes_configured": {"type": "boolean"},
            "shared_memory_configured": {"type": "boolean"},
            "operational_read_configured": {"type": "boolean"},
            "action_proposals_configured": {"type": "boolean"},
            "action_execution_exposed": {"type": "boolean"},
            "gpt_action_schema": {"type": "string"},
        },
        ["ok", "service"],
    )

    context_response = _object(
        {
            "databaseReady": {"type": "boolean"},
            "readOnly": {"type": "boolean"},
            "sourceOfTruth": {"type": "string"},
            "accessMode": {"type": "string"},
            "topic": {"type": "string"},
        },
        ["readOnly", "sourceOfTruth"],
    )

    knowledge_fact = _object(
        {
            "statement": {"type": "string"},
            "scope_type": {
                "type": "string",
                "enum": ["GLOBAL", "SITE", "VENDOR", "ITEM", "WORKFLOW"],
            },
            "topic": {"type": "string"},
        },
        ["statement"],
    )
    knowledge_request = _object(
        {
            "source_ref": {"type": "string"},
            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
            "vendor": {"type": "string"},
            "user_message": {"type": "string"},
            "facts": {"type": "array", "items": knowledge_fact},
        },
        ["source_ref", "user_message", "facts"],
    )
    knowledge_response = _object(
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

    po_record = _object(
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
    po_response = _object(
        {
            "items": {"type": "array", "items": po_record},
            "count": {"type": "integer"},
            "readOnly": {"type": "boolean"},
            "sourceOfTruth": {"type": "string"},
        },
        ["items", "count", "readOnly"],
    )

    receiving_base_properties: dict[str, Any] = {
        "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
        "text": {"type": "string"},
        "vendor_code": {"type": "string"},
        "purchase_order_id": {"type": "integer"},
        "received_at": {"type": "string", "format": "date-time"},
        "source_external_id": {"type": "string"},
        "reporter": {"type": "string"},
    }
    receiving_preview_request = _object(dict(receiving_base_properties), ["site", "text"])
    receiving_preview_response = _object(
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
            "confirmationToken": {"type": "string"},
            "confirmationExpiresInSeconds": {"type": "integer"},
            "commitBlockReason": {"type": "string"},
        },
        ["committed", "canCommit", "commitEligible", "site", "readOnly", "operationalMutation"],
    )

    commit_properties = dict(receiving_base_properties)
    commit_properties.update(
        {
            "confirmation_token": {"type": "string"},
            "confirmation": {"type": "string", "enum": ["COMMIT TRUE"]},
        }
    )
    receiving_commit_request = _object(
        commit_properties,
        ["site", "text", "confirmation_token", "confirmation"],
    )
    receiving_commit_response = _object(
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

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SPPG Hermes Lab",
            "version": app.version,
            "description": "Minimal static OpenAPI contract for Hermes SPPG GPT Actions.",
        },
        "servers": [{"url": public_origin}],
        "paths": {
            "/health": {
                "get": {
                    "operationId": "hermesLabHealth",
                    "summary": "Check Hermes Lab health",
                    "responses": {"200": _json_response(health_response)},
                }
            },
            "/v1/lab/context": {
                "get": {
                    "operationId": "readHermesSppgContext",
                    "summary": "Read Hermes SPPG context",
                    "parameters": [
                        _query("site", {"type": "string", "enum": ["MAJA", "CEMPLANG"]}),
                        _query("vendor", {"type": "string"}),
                        _query("topic", {"type": "string", "enum": ["all", "knowledge", "behavior", "procurement", "po", "receiving", "payment", "payments"]}),
                        _query("q", {"type": "string"}),
                        _query("asOf", {"type": "string", "format": "date"}),
                        _query("limit", {"type": "integer", "minimum": 1, "maximum": 50}),
                    ],
                    "responses": {"200": _json_response(context_response)},
                }
            },
            "/v1/lab/knowledge": {
                "post": {
                    "operationId": "storeHermesKnowledge",
                    "summary": "Store explicit confirmed knowledge",
                    "requestBody": _body(knowledge_request),
                    "responses": {"200": _json_response(knowledge_response)},
                }
            },
            "/v1/lab/purchase-orders": {
                "get": {
                    "operationId": "searchHermesSppgPurchaseOrders",
                    "summary": "Search SPPG purchase orders read-only",
                    "parameters": [
                        _query("site", {"type": "string", "enum": ["MAJA", "CEMPLANG"]}),
                        _query("vendor", {"type": "string"}),
                        _query("distributionDate", {"type": "string", "format": "date"}),
                        _query("dateFrom", {"type": "string", "format": "date"}),
                        _query("dateTo", {"type": "string", "format": "date"}),
                        _query("status", {"type": "string"}),
                        _query("limit", {"type": "integer", "minimum": 1, "maximum": 200}),
                    ],
                    "responses": {"200": _json_response(po_response)},
                }
            },
            "/v1/lab/receiving-preview": {
                "post": {
                    "operationId": "previewHermesReceivingMultiPo",
                    "summary": "Preview receiving without mutation",
                    "requestBody": _body(receiving_preview_request),
                    "responses": {"200": _json_response(receiving_preview_response)},
                }
            },
            "/v1/lab/receiving-commit": {
                "post": {
                    "operationId": "commitHermesReceiving",
                    "summary": "Commit receiving after explicit COMMIT TRUE confirmation",
                    "requestBody": _body(receiving_commit_request),
                    "responses": {"200": _json_response(receiving_commit_response)},
                }
            },
        },
    }


# The schema route defined in hermes_lab.app resolves this symbol at request time.
# Replacing it here changes only the GPT-facing OpenAPI document, not runtime routes.
base._build_chatgpt_action_schema = build_chatgpt_action_schema_static
