from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.operations_action_schema_v017_api import schema_v0172

router = APIRouter(tags=["chatgpt-schema"])


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        value["required"] = required
    return value


def finance_item_schema() -> dict[str, Any]:
    return obj(
        {
            "transaction_id": {"type": ["string", "null"]},
            "date": {"type": "string", "format": "date"},
            "description": {"type": "string", "minLength": 1},
            "type": {"type": "string", "enum": ["income", "expense"]},
            "category": {"type": "string", "minLength": 1},
            "amount": {"type": "number", "minimum": 0},
            "qty": {"type": ["number", "null"]},
            "unit": {"type": ["string", "null"]},
            "unit_price": {"type": ["number", "null"], "minimum": 0},
            "order_by": {"type": ["string", "null"]},
            "is_debt": {"type": "boolean", "default": False},
            "payment_status": {
                "type": "string",
                "enum": ["paid", "unpaid", "partial"],
                "default": "paid",
            },
            "paid_amount": {"type": ["number", "null"], "minimum": 0},
            "paid_date": {"type": ["string", "null"], "format": "date"},
            "classification_confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "default": 1,
            },
            "classification_reason": {"type": "string"},
            "note": {"type": "string"},
        },
        ["date", "description", "type", "category", "amount"],
    )


def finance_record_schema() -> dict[str, Any]:
    return obj(
        {
            "transaction_id": {"type": "string"},
            "site": {"type": "string"},
            "transaction_date": {"type": "string", "format": "date"},
            "description": {"type": "string"},
            "transaction_type": {"type": "string"},
            "category": {"type": "string"},
            "amount": {"type": "number"},
            "qty": {"type": ["number", "null"]},
            "unit": {"type": ["string", "null"]},
            "unit_price": {"type": ["number", "null"]},
            "order_by": {"type": ["string", "null"]},
            "is_debt": {"type": "boolean"},
            "payment_status": {"type": "string"},
            "paid_amount": {"type": "number"},
            "paid_date": {"type": ["string", "null"], "format": "date"},
            "source": {"type": "string"},
            "source_ref": {"type": ["string", "null"]},
            "firestore_sync_status": {"type": ["string", "null"]},
            "firestore_doc_id": {"type": ["string", "null"]},
            "note": {"type": ["string", "null"]},
        }
    )


def _bridge_status_operation() -> dict[str, Any]:
    return {
        "get": {
            "operationId": "getSppgAccountantBridgeStatus",
            "summary": "Check the SPPG Accountant database and Firestore bridge",
            "description": "READ-ONLY. Checks whether PostgreSQL, Google credentials, raw-chat archive, and the configured Firestore project are available.",
            "x-openai-isConsequential": False,
            "responses": {
                "200": {
                    "description": "Bridge status",
                    "content": {
                        "application/json": {
                            "schema": obj(
                                {
                                    "databaseReady": {"type": "boolean"},
                                    "googleCredentialsConfigured": {"type": "boolean"},
                                    "rawChatFolderConfigured": {"type": "boolean"},
                                    "firestoreProject": {"type": "string"},
                                }
                            )
                        }
                    },
                }
            },
        }
    }


def _finance_transactions_operation() -> dict[str, Any]:
    sync_result = obj(
        {
            "transactionId": {"type": "string"},
            "inserted": {"type": "boolean"},
            "firestoreSyncStatus": {"type": "string"},
            "firestoreDocument": {"type": ["string", "null"]},
            "syncError": {"type": ["string", "null"]},
        }
    )
    return {
        "get": {
            "operationId": "searchSppgAccountantTransactions",
            "summary": "Search recorded MAJA or CEMPLANG Accountant transactions",
            "description": "READ-ONLY. Searches the central PostgreSQL finance ledger used by the Accountant bridge. Use explicit site/date/text filters when provided; do not invent missing filters.",
            "x-openai-isConsequential": False,
            "parameters": [
                {
                    "in": "query",
                    "name": "site",
                    "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                },
                {"in": "query", "name": "from", "schema": {"type": "string", "format": "date"}},
                {"in": "query", "name": "to", "schema": {"type": "string", "format": "date"}},
                {
                    "in": "query",
                    "name": "payment_status",
                    "schema": {"type": "string", "enum": ["paid", "unpaid", "partial"]},
                },
                {"in": "query", "name": "q", "schema": {"type": "string"}},
                {
                    "in": "query",
                    "name": "limit",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                },
            ],
            "responses": {
                "200": {
                    "description": "Matching Accountant transactions",
                    "content": {
                        "application/json": {
                            "schema": obj(
                                {"items": {"type": "array", "items": finance_record_schema()}},
                                ["items"],
                            )
                        }
                    },
                }
            },
        },
        "post": {
            "operationId": "createSppgAccountantTransactions",
            "summary": "Record verified income or expense in the SPPG Accountant bridge",
            "description": "Writes verified transactions to PostgreSQL and attempts Firestore sync for the selected Accountant site. Never invent site, date, amount, type, or category. Reuse source_ref on retries and report every sync result.",
            "x-openai-isConsequential": True,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": obj(
                            {
                                "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                                "source_ref": {"type": "string", "minLength": 1, "maxLength": 240},
                                "raw_text": {"type": "string"},
                                "actor": {"type": "string", "default": "chatgpt"},
                                "archive_raw_text": {"type": "boolean", "default": True},
                                "items": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 100,
                                    "items": finance_item_schema(),
                                },
                            },
                            ["site", "source_ref", "items"],
                        )
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Persisted transactions and Firestore sync results",
                    "content": {
                        "application/json": {
                            "schema": obj(
                                {
                                    "site": {"type": "string"},
                                    "sourceRef": {"type": "string"},
                                    "evidenceUri": {"type": ["string", "null"]},
                                    "archiveError": {"type": ["string", "null"]},
                                    "count": {"type": "integer"},
                                    "items": {"type": "array", "items": sync_result},
                                }
                            )
                        }
                    },
                }
            },
        },
    }


def _finance_patch_operation() -> dict[str, Any]:
    patch_properties = deepcopy(finance_item_schema()["properties"])
    patch_properties.pop("transaction_id", None)
    patch_properties.pop("type", None)
    for prop in patch_properties.values():
        if isinstance(prop.get("type"), str):
            prop["type"] = [prop["type"], "null"]
        if isinstance(prop.get("enum"), list) and None not in prop["enum"]:
            prop["enum"] = [*prop["enum"], None]
        prop.pop("default", None)
    patch_properties["category_override_reason"] = {"type": ["string", "null"]}
    patch_properties["actor"] = {"type": "string", "default": "chatgpt"}
    return {
        "patch": {
            "operationId": "updateSppgAccountantTransaction",
            "summary": "Correct a recorded Accountant transaction or payment status",
            "description": "Updates an existing PostgreSQL finance transaction and attempts to synchronize the same Accountant document in Firestore. Use only explicit corrections and report the returned sync status.",
            "x-openai-isConsequential": True,
            "parameters": [
                {
                    "in": "path",
                    "name": "transaction_id",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": obj(patch_properties)}},
            },
            "responses": {
                "200": {
                    "description": "Updated transaction and Firestore sync result",
                    "content": {
                        "application/json": {
                            "schema": obj(
                                {
                                    "transactionId": {"type": "string"},
                                    "changed": {"type": "boolean"},
                                    "firestoreSyncStatus": {"type": ["string", "null"]},
                                    "firestoreDocument": {"type": ["string", "null"]},
                                    "syncError": {"type": ["string", "null"]},
                                }
                            )
                        }
                    },
                }
            },
        }
    }


def _firestore_backfill_operation() -> dict[str, Any]:
    return {
        "post": {
            "operationId": "previewOrBackfillSppgAccountantFirestoreHistory",
            "summary": "Preview or import existing Accountant Firestore history into PostgreSQL",
            "description": "Use dry_run=true first. This reads existing MAJA/CEMPLANG Accountant Firestore records without changing them. Import only with dry_run=false after review; existing PostgreSQL records are skipped idempotently.",
            "x-openai-isConsequential": True,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": obj(
                            {
                                "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                                "dry_run": {"type": "boolean", "default": True},
                                "batch_size": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
                                "start_after_id": {"type": ["string", "null"]},
                                "actor": {"type": "string", "default": "chatgpt"},
                            },
                            ["site", "dry_run"],
                        )
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Firestore history preview or import batch result",
                    "content": {
                        "application/json": {
                            "schema": obj(
                                {
                                    "site": {"type": "string"},
                                    "dryRun": {"type": "boolean"},
                                    "firestoreRead": {"type": "integer"},
                                    "importable": {"type": "integer"},
                                    "alreadyPresent": {"type": "integer"},
                                    "inserted": {"type": "integer"},
                                    "invalid": {"type": "integer"},
                                    "failed": {"type": "integer"},
                                    "hasMore": {"type": "boolean"},
                                    "nextCursor": {"type": ["string", "null"]},
                                    "errors": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                                    "sample": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                                }
                            )
                        }
                    },
                }
            },
        }
    }


def _po_whatsapp_operation() -> dict[str, Any]:
    item = obj(
        {
            "id": {"type": "integer"},
            "item_name": {"type": "string"},
            "po_qty": {"type": "number"},
            "unit": {"type": ["string", "null"]},
        }
    )
    return {
        "get": {
            "operationId": "getFinalSppgPurchaseOrderWhatsAppMessage",
            "summary": "Get a final edited PO and its WhatsApp-ready vendor message",
            "description": "READ-ONLY. Returns only a saved final PO from Pusat Kontrol, never raw calculator planning. Provide purchaseOrderId or site, vendor, and distributionDate. If still DRAFT, ask the operator to finish and finalize it first.",
            "x-openai-isConsequential": False,
            "parameters": [
                {"in": "query", "name": "purchaseOrderId", "schema": {"type": "integer"}},
                {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                {"in": "query", "name": "vendor", "schema": {"type": "string"}},
                {"in": "query", "name": "distributionDate", "schema": {"type": "string", "format": "date"}},
            ],
            "responses": {
                "200": {
                    "description": "Final PO and canonical WhatsApp text",
                    "content": {
                        "application/json": {
                            "schema": obj(
                                {
                                    "purchaseOrderId": {"type": "integer"},
                                    "poCode": {"type": "string"},
                                    "site": {"type": "string"},
                                    "vendorCode": {"type": "string"},
                                    "vendorName": {"type": "string"},
                                    "distributionDate": {"type": "string", "format": "date"},
                                    "status": {"type": "string"},
                                    "whatsappPhone": {"type": ["string", "null"]},
                                    "readyToSend": {"type": "boolean"},
                                    "message": {"type": "string"},
                                    "items": {"type": "array", "items": item},
                                }
                            )
                        }
                    },
                }
            },
        }
    }


def schema_v0180() -> dict[str, Any]:
    payload = deepcopy(schema_v0172())
    payload["info"] = {
        "title": "SPPG Operations and Accountant Bridge",
        "version": "0.18.0",
        "description": (
            "The complete v0.17.2 operations workflow plus final PO WhatsApp retrieval "
            "and MAJA/CEMPLANG Accountant finance transaction access."
        ),
    }
    payload["paths"]["/v1/gpt/status"] = _bridge_status_operation()
    payload["paths"]["/v1/gpt/finance-transactions"] = _finance_transactions_operation()
    payload["paths"]["/v1/gpt/finance-transactions/{transaction_id}"] = _finance_patch_operation()
    payload["paths"]["/v1/gpt/backfill-firestore"] = _firestore_backfill_operation()
    payload["paths"]["/v1/po-whatsapp-preview"] = _po_whatsapp_operation()
    return payload


@router.get("/schema/chatgpt-sppg-v0180.json", include_in_schema=False)
def chatgpt_sppg_schema_v0180() -> JSONResponse:
    return JSONResponse(schema_v0180())
