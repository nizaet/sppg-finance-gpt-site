from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.operations_action_schema_api import schema as operations_schema_v0163

router = APIRouter(tags=["chatgpt-schema"])


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    return out


def schema_v0170() -> dict[str, Any]:
    """Return the original v0.17.0 schema without modifying its 11 actions."""
    payload = operations_schema_v0163()
    payload["info"]["version"] = "0.17.0"
    payload["info"]["description"] = "SPPG operations with safe historical PO and goods-receipt reconstruction, invoice parsing, payables, payments, and inventory."
    components = payload.setdefault("components", {})
    components["schemas"] = {}

    po_line = obj({
        "item_name": {"type": "string"},
        "po_qty": {"type": "number", "minimum": 0},
        "unit": {"type": ["string", "null"]},
        "item_code": {"type": ["string", "null"]},
        "planned_qty": {"type": ["number", "null"], "minimum": 0},
        "planning_price": {"type": ["number", "null"], "minimum": 0},
        "po_price": {"type": ["number", "null"], "minimum": 0},
        "notes": {"type": ["string", "null"]},
    }, ["item_name", "po_qty"])
    receipt_line = obj({
        "item_name": {"type": "string"},
        "received_qty": {"type": ["number", "null"], "minimum": 0},
        "rejected_qty": {"type": "number", "minimum": 0, "default": 0},
        "accepted_qty": {"type": ["number", "null"], "minimum": 0},
        "unit": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    }, ["item_name"])
    warning = obj({
        "code": {"type": "string"},
        "item": {"type": ["string", "null"]},
        "message": {"type": "string"},
    })
    receipt_preview = obj({
        "reported_item_name": {"type": "string"},
        "matched_po_item_name": {"type": "string"},
        "match_confidence": {"type": "number"},
        "po_qty": {"type": "number"},
        "received_qty": {"type": "number"},
        "rejected_qty": {"type": "number"},
        "accepted_qty": {"type": "number"},
        "variance_qty": {"type": "number"},
        "unit": {"type": ["string", "null"]},
    })

    payload["paths"]["/v1/operations/history/import"] = {
        "post": {
            "operationId": "previewOrImportSppgHistoricalOperations",
            "summary": "Preview or import verified historical PO and receiving evidence",
            "description": "Use commit=false first. Import only verified historical evidence. Unknown received quantities stay unknown; never infer them from rejects or invoices. No finance transaction is created.",
            "x-openai-isConsequential": True,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": obj({
                            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                            "vendor_code": {"type": "string"},
                            "distribution_date": {"type": "string", "format": "date"},
                            "po_code": {"type": ["string", "null"]},
                            "source_type": {"type": "string"},
                            "source_external_id": {"type": ["string", "null"]},
                            "source_uri": {"type": ["string", "null"]},
                            "source_raw_text": {"type": ["string", "null"]},
                            "received_at": {"type": ["string", "null"], "format": "date-time"},
                            "po_lines": {"type": "array", "minItems": 1, "items": po_line},
                            "receipt_lines": {"type": "array", "items": receipt_line},
                            "commit": {"type": "boolean", "default": False},
                        }, ["site", "vendor_code", "distribution_date", "source_type", "po_lines", "commit"])
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Historical operational preview or import result",
                    "content": {
                        "application/json": {
                            "schema": obj({
                                "committed": {"type": "boolean"},
                                "duplicate": {"type": "boolean"},
                                "canCommit": {"type": "boolean"},
                                "historicalImport": {"type": "boolean"},
                                "site": {"type": "string"},
                                "vendorCode": {"type": "string"},
                                "distributionDate": {"type": "string", "format": "date"},
                                "poCode": {"type": "string"},
                                "poCodeGenerated": {"type": "boolean"},
                                "sourceType": {"type": "string"},
                                "sourceHash": {"type": "string"},
                                "purchaseOrderId": {"type": ["integer", "null"]},
                                "goodsReceiptId": {"type": ["integer", "null"]},
                                "status": {"type": ["string", "null"]},
                                "poLines": {"type": "array", "items": po_line},
                                "receiptLinesEligible": {"type": "array", "items": receipt_preview},
                                "receiptLinesSkipped": {"type": "integer"},
                                "warnings": {"type": "array", "items": warning},
                                "financeTransactionCreated": {"type": "boolean"},
                            })
                        }
                    },
                }
            },
        }
    }
    return payload


def _current_receiving_operation() -> dict[str, Any]:
    receipt_preview = obj({
        "reported_item_name": {"type": "string"},
        "po_item_name": {"type": ["string", "null"]},
        "purchase_order_item_id": {"type": ["integer", "null"]},
        "matched": {"type": "boolean"},
        "match_confidence": {"type": "number"},
        "match_method": {"type": "string"},
        "po_qty": {"type": ["number", "null"]},
        "received_qty": {"type": "number"},
        "variance_qty": {"type": ["number", "null"]},
        "unit": {"type": ["string", "null"]},
    })
    return {
        "post": {
            "operationId": "previewOrRecordSppgGoodsReceiptFromMessage",
            "summary": "Preview or record a current goods receipt from supplied message text",
            "description": (
                "Use only the receipt text supplied by the user. Always call with commit=false first. "
                "Commit only after the PO and every item match safely or after the user supplies the exact purchase_order_id. "
                "A committed receipt is stored in PostgreSQL and appears in Pusat Operasional > Penerimaan. "
                "Never overwrite planned_qty or po_qty."
            ),
            "x-openai-isConsequential": True,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": obj({
                            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                            "text": {"type": "string", "minLength": 1},
                            "vendor_code": {"type": ["string", "null"]},
                            "purchase_order_id": {"type": ["integer", "null"]},
                            "received_at": {"type": ["string", "null"], "format": "date-time"},
                            "source_external_id": {"type": ["string", "null"]},
                            "source_uri": {"type": ["string", "null"]},
                            "reporter": {"type": ["string", "null"]},
                            "commit": {"type": "boolean", "default": False},
                        }, ["site", "text", "commit"])
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Goods receipt preview or commit result",
                    "content": {
                        "application/json": {
                            "schema": obj({
                                "committed": {"type": "boolean"},
                                "canCommit": {"type": "boolean"},
                                "duplicate": {"type": ["boolean", "null"]},
                                "site": {"type": "string"},
                                "vendorCode": {"type": ["string", "null"]},
                                "purchaseOrderId": {"type": ["integer", "null"]},
                                "poCode": {"type": ["string", "null"]},
                                "poMatchConfidence": {"type": ["number", "null"]},
                                "requiresConfirmation": {"type": ["boolean", "null"]},
                                "receiptId": {"type": ["integer", "null"]},
                                "purchaseOrderStatus": {"type": ["string", "null"]},
                                "matches": {"type": "array", "items": receipt_preview},
                                "alternatives": {"type": "array", "items": obj({
                                    "purchase_order_id": {"type": "integer"},
                                    "po_code": {"type": "string"},
                                    "vendor_code": {"type": "string"},
                                    "score": {"type": "number"},
                                })},
                            })
                        }
                    },
                }
            },
        }
    }


def schema_v0171() -> dict[str, Any]:
    payload = deepcopy(schema_v0170())
    payload["info"]["version"] = "0.17.1"
    payload["info"]["description"] = "SPPG operations with safe current and historical receiving, invoice parsing, payables, payments, and inventory."
    payload["paths"]["/v1/receiving/whatsapp"] = _current_receiving_operation()
    return payload


def _chat_staging_operation() -> dict[str, Any]:
    parsed_event = obj({
        "event_id": {"type": "string"},
        "event_type": {"type": "string"},
        "confidence": {"type": "number"},
        "requires_confirmation": {"type": "boolean"},
        "raw_text": {"type": "string"},
        "actor": {"type": ["string", "null"]},
        "counterparty": {"type": ["string", "null"]},
        "site": {"type": ["string", "null"]},
        "vendor": {"type": ["string", "null"]},
        "structured_payload": {"type": "object", "additionalProperties": True},
    })
    return {
        "post": {
            "operationId": "stageSuppliedSppgWhatsAppActivityForReview",
            "summary": "Store supplied WhatsApp activity in the central review queue",
            "description": (
                "Use for every operational WhatsApp message the user asks to record, including invoice, receiving, payment evidence, "
                "PO revision, vendor price or availability change, quality reject, and pending approval. Preserve the exact supplied text. "
                "This writes an idempotent candidate event to PostgreSQL and makes it visible in Pusat Operasional > Review; it does not "
                "silently create or change a finance transaction, PO, receipt, payable, payment, or stock movement. After staging, use the "
                "specific domain action when the user asks to record that domain transaction."
            ),
            # Staging is idempotent and never mutates a final ledger/domain
            # record. Domain commit actions remain consequential.
            "x-openai-isConsequential": False,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": obj({
                            "text": {"type": "string", "minLength": 1},
                            "source_type": {"type": "string", "default": "GPT_PASTED_WHATSAPP"},
                            "external_id": {"type": ["string", "null"]},
                            "source_uri": {"type": ["string", "null"]},
                            "actor": {"type": ["string", "null"], "default": "chatgpt"},
                            "context_site": {"type": ["string", "null"]},
                            "context_vendor": {"type": ["string", "null"]},
                            "stage": {"type": "boolean", "enum": [True], "default": True},
                        }, ["text", "stage"])
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Staged operational event",
                    "content": {
                        "application/json": {
                            "schema": obj({
                                "parsed": parsed_event,
                                "staged": {"type": "boolean"},
                                "eventId": {"type": ["integer", "null"]},
                                "eventKey": {"type": ["string", "null"]},
                                "status": {"type": ["string", "null"]},
                            })
                        }
                    },
                }
            },
        }
    }


def _review_queue_operation() -> dict[str, Any]:
    review_item = obj({
        "id": {"type": "integer"},
        "event_key": {"type": "string"},
        "event_type": {"type": "string"},
        "site": {"type": ["string", "null"]},
        "vendor_code": {"type": ["string", "null"]},
        "entity_code": {"type": ["string", "null"]},
        "event_time": {"type": ["string", "null"], "format": "date-time"},
        "confidence": {"type": "number"},
        "requires_confirmation": {"type": "boolean"},
        "payload": {"type": "object", "additionalProperties": True},
        "raw_text": {"type": "string"},
        "parser_version": {"type": "string"},
        "status": {"type": "string"},
        "created_at": {"type": ["string", "null"], "format": "date-time"},
    })
    return {
        "get": {
            "operationId": "listSppgPendingOperationalReviews",
            "summary": "Read pending operational events from the central review queue",
            "description": "READ-ONLY. Returns WhatsApp/chat activities waiting for review in Pusat Operasional. Do not claim that a pending event has changed a ledger or domain record.",
            "responses": {
                "200": {
                    "description": "Pending review events",
                    "content": {
                        "application/json": {
                            "schema": obj({"items": {"type": "array", "items": review_item}})
                        }
                    },
                }
            },
        }
    }


def schema_v0172() -> dict[str, Any]:
    payload = deepcopy(schema_v0171())
    payload["info"]["version"] = "0.17.2"
    payload["info"]["description"] = (
        "Original SPPG v0.17.0 operations plus safe current receiving and central WhatsApp/chat staging and review. "
        "All original operation IDs remain unchanged."
    )
    payload["paths"]["/v1/parse-message"] = _chat_staging_operation()
    payload["paths"]["/v1/review-queue"] = _review_queue_operation()
    return payload


def schema_v017() -> dict[str, Any]:
    """Backward-compatible Python entrypoint for the newest v0.17 schema."""
    return schema_v0172()


@router.get("/schema/chatgpt-operations-v0170.json", include_in_schema=False)
def chatgpt_operations_schema_v0170() -> JSONResponse:
    return JSONResponse(schema_v0170())


@router.get("/schema/chatgpt-operations-v0171.json", include_in_schema=False)
def chatgpt_operations_schema_v0171() -> JSONResponse:
    return JSONResponse(schema_v0171())


@router.get("/schema/chatgpt-operations-v0172.json", include_in_schema=False)
def chatgpt_operations_schema_v0172() -> JSONResponse:
    return JSONResponse(schema_v0172())
