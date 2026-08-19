from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend import unified_action_schema_api as schema_api

_ORIGINAL_V0184 = schema_api.schema_v0184
_INSTALLED = False


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        value["required"] = required
    return value


def _knowledge_operation() -> dict[str, Any]:
    return {"get": {
        "operationId": "getSppgOperationalRuntimeContext",
        "summary": "Load canonical SPPG knowledge and live operational context",
        "description": (
            "READ-ONLY FIRST-CONTEXT ACTION. Call this at the start of every new operational conversation before interpreting or committing "
            "PO, receiving, payment, payable, accountant, or warehouse work. Call it again when site/vendor/date context materially changes. "
            "PostgreSQL live state is the source of truth; canonicalKnowledge contains durable operating rules. Do not rely on a previous chat window "
            "when this action can resolve the current context."
        ),
        "x-openai-isConsequential": False,
        "parameters": [
            {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
            {"in": "query", "name": "vendor", "schema": {"type": "string"}},
            {"in": "query", "name": "asOf", "schema": {"type": "string", "format": "date"}},
            {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}},
        ],
        "responses": {"200": {"description": "Canonical knowledge plus live PostgreSQL context", "content": {"application/json": {"schema": _obj({
            "runtimeVersion": {"type": "string"},
            "generatedAt": {"type": "string", "format": "date-time"},
            "asOf": {"type": "string", "format": "date"},
            "databaseReady": {"type": "boolean"},
            "site": {"type": ["string", "null"]},
            "vendorCode": {"type": ["string", "null"]},
            "sourceOfTruth": {"type": "string"},
            "canonicalKnowledge": {"type": "object", "additionalProperties": True},
            "liveContext": {"type": "object", "additionalProperties": True},
            "sectionErrors": {"type": "object", "additionalProperties": True},
            "safeToUseForWrites": {"type": "boolean"},
        })}}}},
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
        "summary": "Record a verified vendor transfer even before payable reconciliation is complete",
        "description": (
            "Use for explicit payment evidence such as 'sudah saya transfer/udah dibayar'. If one payable is uniquely compatible the payment may "
            "reconcile immediately; otherwise commit records PAID_UNRECONCILED instead of rejecting the real transfer. Never ask the user to enter "
            "the same payment again merely because GR/invoice reconciliation is incomplete."
        ),
        "x-openai-isConsequential": True,
        "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
        "responses": {"200": {"description": "Payment evidence preview/commit and reconciliation state", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _payment_reconcile_operation() -> dict[str, Any]:
    return {"post": {
        "operationId": "reconcileRecordedSppgVendorPayment",
        "summary": "Link a paid-unreconciled transfer to its vendor payable",
        "description": (
            "Use after the matching vendor invoice/payable becomes uniquely known. This never creates a second payment or finance transaction; "
            "it only changes reconciliation linkage/status."
        ),
        "x-openai-isConsequential": True,
        "parameters": [{"in": "path", "name": "payment_id", "required": True, "schema": {"type": "integer", "minimum": 1}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": _obj({
            "vendor_invoice_id": {"type": "integer", "minimum": 1},
            "note": {"type": "string"},
            "actor": {"type": "string", "default": "chatgpt"},
            "commit": {"type": "boolean", "default": False},
        }, ["vendor_invoice_id", "commit"])}}},
        "responses": {"200": {"description": "Reconciliation preview/result", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def _unreconciled_operation() -> dict[str, Any]:
    return {"get": {
        "operationId": "listSppgPaidUnreconciledVendorPayments",
        "summary": "List real transfers still waiting for payable reconciliation",
        "description": "READ-ONLY. Reconnect a prior real transfer to a later goods receipt/invoice without asking the user to enter payment again.",
        "x-openai-isConsequential": False,
        "parameters": [
            {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
            {"in": "query", "name": "vendor", "schema": {"type": "string"}},
            {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}},
        ],
        "responses": {"200": {"description": "Paid-unreconciled transfers", "content": {"application/json": {"schema": _obj({
            "items": {"type": "array", "items": {"type": "object", "additionalProperties": True}}
        })}}}},
    }}


def _excel_operation() -> dict[str, Any]:
    return {"post": {
        "operationId": "previewOrGenerateSppgAccountantExcel",
        "summary": "Generate Accountant Excel with Drive fail-safe",
        "description": (
            "Generate the Accountant workbook from the planning snapshot. The XLSX remains downloadable even if Google Drive upload fails. "
            "When driveUploadStatus=FAILED, report that Excel generation succeeded and Drive upload is retryable; do not call it an Excel failure."
        ),
        "x-openai-isConsequential": True,
        "requestBody": {"required": True, "content": {"application/json": {"schema": _obj({
            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
            "distribution_date": {"type": "string", "format": "date"},
            "planning_snapshot_id": {"type": ["integer", "null"]},
            "commit": {"type": "boolean", "default": False},
        }, ["site", "distribution_date", "commit"])}}},
        "responses": {"200": {"description": "Excel generation/upload state", "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}}},
    }}


def schema_v0184_core_repair() -> dict[str, Any]:
    payload = deepcopy(_ORIGINAL_V0184())
    payload["info"] = {
        "title": "SPPG Operations, Runtime Knowledge, and Accountant Bridge",
        "version": "0.18.5",
        "description": (
            "Backward-compatible v0.18.4 action surface plus deterministic multi-PO receiving, paid-unreconciled vendor transfers, "
            "Accountant Excel Drive fail-safe, and a canonical/live operational context runtime. At the start of a new operational conversation, "
            "call getSppgOperationalRuntimeContext before relying on prior-chat memory."
        ),
    }
    paths = payload.setdefault("paths", {})
    paths["/v1/gpt/operational-context"] = _knowledge_operation()
    paths["/v1/vendor-payments/record-evidence"] = _payment_evidence_operation()
    paths["/v1/vendor-payments/{payment_id}/reconcile"] = _payment_reconcile_operation()
    paths["/v1/vendor-payments/unreconciled"] = _unreconciled_operation()
    paths["/v1/accountant-excel/from-planning"] = _excel_operation()

    receiving = paths.get("/v1/receiving/whatsapp", {}).get("post")
    if receiving:
        receiving["summary"] = "Preview or record a deterministic goods receipt across one or more POs"
        receiving["description"] = (
            "Resolve supplied receiving text against the complete relevant open-PO pool for the same site/vendor. One report may allocate one item "
            "across main/additional/late POs using item identity, unit, date relevance, and outstanding qty. Do not require one purchase_order_id when "
            "allocation is deterministic. If canCommit=true and the user explicitly says commit, execute. Ask only when the endpoint reports a genuine "
            "item-family or vendor ambiguity."
        )
    return payload


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    schema_api.schema_v0184 = schema_v0184_core_repair
    _INSTALLED = True
