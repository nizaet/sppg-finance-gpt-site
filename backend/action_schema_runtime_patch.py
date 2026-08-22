from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend import unified_action_schema_api as schema_api

_ORIGINAL_V0184 = schema_api.schema_v0184
_INSTALLED = False

# GPT Builder currently accepts at most 30 operations in one imported OpenAPI
# document. These one-off/admin workflows remain available in SPPG Core and the
# web application; they are omitted only from the primary Custom GPT schema.
_GPT_ACTION_OPERATION_LIMIT = 30
_SCHEMA_ONLY_EXCLUDED_PATHS = {
    "/v1/operations/history/import",
    "/v1/gpt/backfill-firestore",
    "/v1/calculator-data/plan-preview",
    "/v1/calculator-data/import",
    "/v1/accountant-excel/from-planning",
}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        value["required"] = required
    return value


def _knowledge_operation() -> dict[str, Any]:
    return {"get": {
        "operationId": "getSppgOperationalRuntimeContext",
        "summary": "Load canonical, learned, and live SPPG operational context",
        "description": "READ-ONLY. Call at the start of every operational turn with q set to the user's current topic. Returns canonical rules, learned GPT conversation memory, and live PostgreSQL state. Never rely on prior-chat memory alone.",
        "x-openai-isConsequential": False,
        "parameters": [
            {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
            {"in": "query", "name": "vendor", "schema": {"type": "string"}},
            {"in": "query", "name": "q", "schema": {"type": "string", "maxLength": 500}},
            {"in": "query", "name": "asOf", "schema": {"type": "string", "format": "date"}},
            {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}},
        ],
        "responses": {"200": {"description": "Canonical knowledge, learned conversation memory, and live PostgreSQL context", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _learn_conversation_operation() -> dict[str, Any]:
    fact = _obj({
        "statement": {"type": "string", "minLength": 3, "maxLength": 1500},
        "kind": {"type": "string", "enum": ["USER_EXPLICIT", "USER_CORRECTION", "ACTION_CONFIRMED", "ASSISTANT_INFERENCE"]},
        "scope_type": {"type": "string", "enum": ["GLOBAL", "SITE", "VENDOR", "ITEM", "WORKFLOW"], "default": "GLOBAL"},
        "topic": {"type": ["string", "null"], "maxLength": 160},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1},
        "metadata": {"type": "object", "additionalProperties": True},
    }, ["statement", "kind"])
    body = _obj({
        "conversation_ref": {"type": "string", "minLength": 1, "maxLength": 200},
        "turn_ref": {"type": ["string", "null"], "maxLength": 200},
        "site": {"type": ["string", "null"], "enum": ["MAJA", "CEMPLANG", None]},
        "vendor": {"type": ["string", "null"], "maxLength": 100},
        "user_message": {"type": "string", "minLength": 1, "maxLength": 20000},
        "assistant_summary": {"type": ["string", "null"], "maxLength": 6000},
        "action_context": {"type": "object", "additionalProperties": True},
        "facts": {"type": "array", "maxItems": 30, "items": fact},
        "actor": {"type": "string", "default": "chatgpt", "maxLength": 100},
    }, ["conversation_ref", "user_message"])
    return {"post": {
        "operationId": "learnSppgConversationTurn",
        "summary": "Store each GPT turn and promote durable operational knowledge",
        "description": "AUTOMATIC MEMORY WRITE. Call after every meaningful user turn. Archive the user message and summarize useful context. Promote explicit facts, corrections, and action-confirmed results; mark uncertain inference as ASSISTANT_INFERENCE.",
        "x-openai-isConsequential": False,
        "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
        "responses": {"200": {"description": "Conversation memory write", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _explicit_knowledge_operation() -> dict[str, Any]:
    fact = _obj({
        "statement": {"type": "string", "minLength": 3, "maxLength": 1500},
        "scope_type": {"type": "string", "enum": ["GLOBAL", "SITE", "VENDOR", "ITEM", "WORKFLOW"], "default": "GLOBAL"},
        "topic": {"type": ["string", "null"], "maxLength": 160},
        "metadata": {"type": "object", "additionalProperties": True},
    }, ["statement"])
    body = _obj({
        "source_ref": {"type": "string", "minLength": 1, "maxLength": 200},
        "site": {"type": ["string", "null"], "enum": ["MAJA", "CEMPLANG", None]},
        "vendor": {"type": ["string", "null"], "maxLength": 100},
        "user_message": {"type": "string", "minLength": 1, "maxLength": 20000},
        "facts": {"type": "array", "minItems": 1, "maxItems": 30, "items": fact},
        "actor": {"type": "string", "default": "chatgpt", "maxLength": 100},
    }, ["source_ref", "user_message", "facts"])
    return {"post": {
        "operationId": "recordExplicitSppgKnowledge",
        "summary": "Store explicitly requested facts as confirmed LLM Wiki knowledge",
        "description": "MEMORY ONLY. Use when the user says catat, ingat, or masukkan ke LLM Wiki/knowledge. Confirm explicit rules, corrections, mappings, and unit conversions here; never send them to operational review.",
        "x-openai-isConsequential": False,
        "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
        "responses": {"200": {"description": "Confirmed knowledge write", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _payment_evidence_operation() -> dict[str, Any]:
    body = _obj({
        "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
        "vendor_code": {"type": "string", "minLength": 1},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "paid_at": {"type": ["string", "null"], "format": "date-time"},
        "payment_source": {"type": ["string", "null"]},
        "reference_number": {"type": ["string", "null"]},
        "evidence_uri": {"type": ["string", "null"]},
        "source_external_id": {"type": ["string", "null"]},
        "purchase_order_id": {"type": ["integer", "null"]},
        "goods_receipt_id": {"type": ["integer", "null"]},
        "vendor_invoice_id": {"type": ["integer", "null"]},
        "note": {"type": "string"},
        "actor": {"type": "string", "default": "chatgpt"},
        "commit": {"type": "boolean", "default": False},
    }, ["site", "vendor_code", "amount", "commit"])
    return {"post": {
        "operationId": "previewOrRecordSppgVendorPaymentEvidence",
        "summary": "Record a verified vendor transfer",
        "description": "Use when a vendor transfer is confirmed. If one payable matches safely, reconcile it; otherwise commit as PAID_UNRECONCILED.",
        "x-openai-isConsequential": True,
        "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
        "responses": {"200": {"description": "Payment state", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _payment_reconcile_operation() -> dict[str, Any]:
    return {"post": {
        "operationId": "reconcileRecordedSppgVendorPayment",
        "summary": "Link a paid-unreconciled transfer to its vendor payable",
        "description": "Link an existing paid-unreconciled transfer to one verified invoice. Never create a second payment or finance transaction.",
        "x-openai-isConsequential": True,
        "parameters": [{"in": "path", "name": "payment_id", "required": True, "schema": {"type": "integer", "minimum": 1}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": _obj({
            "vendor_invoice_id": {"type": "integer", "minimum": 1},
            "note": {"type": "string"},
            "actor": {"type": "string", "default": "chatgpt"},
            "commit": {"type": "boolean", "default": False},
        }, ["vendor_invoice_id", "commit"])}}},
        "responses": {"200": {"description": "Reconciliation result", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _unreconciled_operation() -> dict[str, Any]:
    return {"get": {
        "operationId": "listSppgPaidUnreconciledVendorPayments",
        "summary": "List real transfers still waiting for payable reconciliation",
        "description": "READ-ONLY. Find recorded transfers waiting to be linked to a later goods receipt or invoice.",
        "x-openai-isConsequential": False,
        "parameters": [
            {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
            {"in": "query", "name": "vendor", "schema": {"type": "string"}},
            {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}},
        ],
        "responses": {"200": {"description": "Paid-unreconciled transfers", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _excel_operation() -> dict[str, Any]:
    return {"post": {
        "operationId": "previewOrGenerateSppgAccountantExcel",
        "summary": "Generate Accountant Excel with Drive fail-safe",
        "description": "Generate Accountant XLSX from planning. XLSX stays downloadable if Drive upload fails.",
        "x-openai-isConsequential": True,
        "requestBody": {"required": True, "content": {"application/json": {"schema": _obj({
            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
            "distribution_date": {"type": "string", "format": "date"},
            "planning_snapshot_id": {"type": ["integer", "null"]},
            "commit": {"type": "boolean", "default": False},
        }, ["site", "distribution_date", "commit"])}}},
        "responses": {"200": {"description": "Excel generation/upload state", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _bgn_approve_operation() -> dict[str, Any]:
    return {"post": {
        "operationId": "confirmSppgBgnMakerApproved",
        "summary": "Confirm a BGN Maker has been approved",
        "description": "Use when the user explicitly confirms a specific Maker is already approved. Preview with commit=false; write only after explicit confirmation.",
        "x-openai-isConsequential": True,
        "parameters": [{"in": "path", "name": "maker_id", "required": True, "schema": {"type": "integer", "minimum": 1}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": _obj({
            "commit": {"type": "boolean", "default": False},
            "approved_at": {"type": ["string", "null"], "format": "date-time"},
            "note": {"type": ["string", "null"]},
            "actor": {"type": "string", "default": "chatgpt"},
        }, ["commit"])}}},
        "responses": {"200": {"description": "Approval confirmation", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _bgn_paid_operation() -> dict[str, Any]:
    return {"post": {
        "operationId": "confirmSppgBgnMakerPaid",
        "summary": "Confirm a BGN Maker payment was received",
        "description": "Use when the user explicitly confirms a specific Maker has been paid/received. This creates or updates the BGN receipt and marks Maker PAID. evidence_uri is optional for GPT; the web UI can upload the proof file to Drive.",
        "x-openai-isConsequential": True,
        "parameters": [{"in": "path", "name": "maker_id", "required": True, "schema": {"type": "integer", "minimum": 1}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": _obj({
            "commit": {"type": "boolean", "default": False},
            "paid_at": {"type": ["string", "null"], "format": "date-time"},
            "evidence_uri": {"type": ["string", "null"]},
            "note": {"type": ["string", "null"]},
            "actor": {"type": "string", "default": "chatgpt"},
        }, ["commit"])}}},
        "responses": {"200": {"description": "Paid confirmation", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def schema_v0184_core_repair() -> dict[str, Any]:
    payload = deepcopy(_ORIGINAL_V0184())
    payload["info"] = {
        "title": "SPPG Operations, Runtime Knowledge, Accountant and BGN Bridge",
        "version": "0.18.9",
        "description": "Stable v0.18.4 URL with explicit LLM Wiki writes, shared GPT/Hermes memory, guarded operational workflows, and a GPT Builder-safe operation count.",
    }
    paths = payload.setdefault("paths", {})
    paths["/v1/gpt/operational-context"] = _knowledge_operation()
    paths["/v1/gpt/learn-conversation"] = _learn_conversation_operation()
    paths["/v1/gpt/knowledge"] = _explicit_knowledge_operation()
    paths["/v1/vendor-payments/record-evidence"] = _payment_evidence_operation()
    paths["/v1/vendor-payments/{payment_id}/reconcile"] = _payment_reconcile_operation()
    paths["/v1/vendor-payments/unreconciled"] = _unreconciled_operation()
    paths["/v1/accountant-excel/from-planning"] = _excel_operation()
    paths["/v1/bgn-makers/{maker_id}/confirm-approved"] = _bgn_approve_operation()
    paths["/v1/bgn-makers/{maker_id}/confirm-paid"] = _bgn_paid_operation()

    for path in _SCHEMA_ONLY_EXCLUDED_PATHS:
        paths.pop(path, None)

    operation_count = sum(
        1
        for path_item in paths.values()
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    )
    if operation_count > _GPT_ACTION_OPERATION_LIMIT:
        raise RuntimeError(
            f"Custom GPT schema exposes {operation_count} operations; "
            f"maximum is {_GPT_ACTION_OPERATION_LIMIT}"
        )

    receiving = paths.get("/v1/receiving/whatsapp", {}).get("post")
    if receiving:
        receiving["summary"] = "Preview or record a deterministic goods receipt across one or more POs"
        receiving["description"] = "Resolve receiving text against all relevant open POs for the same site/vendor. If canCommit=true and the user explicitly says commit, execute; ask only on genuine ambiguity."
    return payload


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    schema_api.schema_v0184 = schema_v0184_core_repair
    _INSTALLED = True
