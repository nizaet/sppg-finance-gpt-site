from __future__ import annotations

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


def schema_v017() -> dict[str, Any]:
    payload = operations_schema_v0163()
    payload["info"]["version"] = "0.17.1"
    payload["info"]["description"] = "SPPG operations with safe current and historical receiving, invoice parsing, payables, payments, and inventory."
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

    payload["paths"]["/v1/receiving/whatsapp"] = {
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


@router.get("/schema/chatgpt-operations-v0170.json", include_in_schema=False)
def chatgpt_operations_schema_v0170() -> JSONResponse:
    return JSONResponse(schema_v017())


@router.get("/schema/chatgpt-operations-v0171.json", include_in_schema=False)
def chatgpt_operations_schema_v0171() -> JSONResponse:
    return JSONResponse(schema_v017())
