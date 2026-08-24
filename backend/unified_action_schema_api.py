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
                                    "coverageDates": {"type": "array", "items": {"type": "string", "format": "date"}},
                                    "coverageDayCount": {"type": "integer"},
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


def _stock_opname_operation() -> dict[str, Any]:
    reviewed_item = obj(
        {
            "client_key": {"type": ["string", "null"]},
            "include": {"type": "boolean", "default": True},
            "area_code": {"type": ["string", "null"]},
            "raw_item_name": {"type": ["string", "null"]},
            "canonical_item_name": {"type": ["string", "null"]},
            "inventory_item_code": {"type": ["string", "null"]},
            "qty": {"type": "number", "minimum": 0},
            "unit": {"type": ["string", "null"]},
            "raw_line": {"type": ["string", "null"]},
        },
        ["qty"],
    )
    parsed_item = obj(
        {
            "clientKey": {"type": "string"},
            "selected": {"type": "boolean"},
            "areaCode": {"type": "string"},
            "itemName": {"type": "string"},
            "canonicalItemName": {"type": "string"},
            "inventoryItemCode": {"type": ["string", "null"]},
            "qty": {"type": "number"},
            "unit": {"type": "string"},
            "classificationStatus": {"type": "string"},
            "classificationMethod": {"type": "string"},
            "classificationConfidence": {"type": "number"},
            "classificationSources": {"type": "array", "items": {"type": "string"}},
            "parseStatus": {"type": "string"},
            "rawLine": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        }
    )
    return {
        "post": {
            "operationId": "previewOrRecordSppgStockOpnameFromWhatsApp",
            "summary": "Preview or record a warehouse stock opname report",
            "description": "One WhatsApp SO is one baseline: preview then commit once. reviewed_items only needs qty; names/keys are taken from the original text when omitted. If no date is written, omit stock_date so Jakarta current date is used.",
            "x-openai-isConsequential": True,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": obj(
                            {
                                "location": {"type": "string", "enum": ["KOPERASI", "MAJA", "CEMPLANG"]},
                                "text": {"type": "string", "minLength": 1},
                                "stock_date": {"type": ["string", "null"], "format": "date"},
                                "source_external_id": {"type": ["string", "null"]},
                                "reporter": {"type": ["string", "null"]},
                                "actor": {"type": "string", "default": "chatgpt"},
                                "reviewed_items": {"type": ["array", "null"], "items": reviewed_item},
                                "commit": {"type": "boolean", "default": False},
                            },
                            ["location", "text", "commit"],
                        )
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "SO preview or persisted baseline",
                    "content": {"application/json": {"schema": obj({
                        "committed": {"type": "boolean"}, "canCommit": {"type": "boolean"},
                        "stockOpnameId": {"type": ["integer", "null"]}, "location": {"type": "string"},
                        "stockDate": {"type": "string", "format": "date"}, "itemCount": {"type": "integer"},
                        "reviewCount": {"type": "integer"}, "unmappedCount": {"type": "integer"},
                        "ambiguousCount": {"type": "integer"}, "warnings": {"type": "array", "items": {"type": "string"}},
                        "items": {"type": "array", "items": parsed_item},
                    })}},
                }
            },
        }
    }


def _projected_inventory_operation() -> dict[str, Any]:
    balance_item = obj({
        "item_name": {"type": "string"},
        "inventory_item_code": {"type": ["string", "null"]},
        "unit": {"type": ["string", "null"]},
        "area_codes": {"type": "array", "items": {"type": "string"}},
        "raw_item_names": {"type": "array", "items": {"type": "string"}},
        "classification_status": {"type": "string"},
        "classification_method": {"type": "string"},
        "so_qty": {"type": "number"},
        "movement_delta": {"type": "number"},
        "actual_usage_depletion": {"type": "number"},
        "planned_depletion": {"type": "number"},
        "balance": {"type": "number"},
        "actual_balance": {"type": "number"},
        "projected_balance": {"type": "number"},
        "available_for_po": {"type": "number"},
        "stock_as_of": {"type": ["string", "null"], "format": "date"},
        "stock_basis": {"type": "string"},
        "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "stock_age_days": {"type": ["integer", "null"]},
    })
    response_schema = obj({
        "site": {"type": "string"},
        "location": {"type": "string"},
        "forDate": {"type": "string", "format": "date"},
        "projectionThrough": {"type": "string", "format": "date"},
        "timezone": {"type": "string"},
        "latestStockOpnameId": {"type": ["integer", "null"]},
        "latestStockOpnameDate": {"type": ["string", "null"], "format": "date"},
        "sameDateStockOpnameIds": {"type": "array", "items": {"type": "integer"}},
        "sameDateStockOpnameCount": {"type": "integer"},
        "baselineNeedsConsolidation": {"type": "boolean"},
        "items": {"type": "array", "items": balance_item},
        "count": {"type": "integer"},
    })
    return {
        "get": {
            "operationId": "readSppgWarehouseStockAndPoProjection",
            "summary": "Read actual and projected stock for a warehouse and PO date",
            "description": "READ-ONLY. Returns the latest SO baseline, later stock facts, actual usage, planned depletion before forDate, confidence, and stock available to reduce that date's PO.",
            "x-openai-isConsequential": False,
            "parameters": [
                {"in": "query", "name": "site", "required": True, "schema": {"type": "string", "enum": ["KOPERASI", "MAJA", "CEMPLANG"]}},
                {"in": "query", "name": "forDate", "schema": {"type": "string", "format": "date"}},
                {"in": "query", "name": "search", "schema": {"type": "string"}},
                {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 300}},
            ],
            "responses": {"200": {"description": "Warehouse balances and projection basis", "content": {"application/json": {"schema": response_schema}}}},
        }
    }


def _inventory_master_operation() -> dict[str, Any]:
    master_item = obj({
        "code": {"type": "string"},
        "canonical_name": {"type": "string"},
        "category_code": {"type": ["string", "null"]},
        "base_unit": {"type": ["string", "null"]},
        "active": {"type": "boolean"},
        "aliases": {"type": "array", "items": {"type": "string"}},
    })
    search_response = obj({
        "items": {"type": "array", "items": master_item},
        "count": {"type": "integer"},
    })
    save_response = obj({
        "committed": {"type": "boolean"},
        "code": {"type": "string"},
        "canonicalName": {"type": "string"},
        "categoryCode": {"type": ["string", "null"]},
        "baseUnit": {"type": ["string", "null"]},
        "aliases": {"type": "array", "items": {"type": "string"}},
    })
    return {
        "get": {
            "operationId": "searchSppgInventoryItemMaster",
            "summary": "Search canonical inventory item types and aliases",
            "description": "READ-ONLY. Use this to classify reported brand or spelling variants by item type. Exact or contained aliases are safe; do not merge different item types.",
            "x-openai-isConsequential": False,
            "parameters": [{"in": "query", "name": "search", "schema": {"type": "string"}}],
            "responses": {"200": {"description": "Canonical items and aliases", "content": {"application/json": {"schema": search_response}}}},
        },
        "post": {
            "operationId": "previewOrSaveSppgInventoryItemMaster",
            "summary": "Preview or save a canonical item type and aliases",
            "description": "Use commit=false first. Save only item types, units, categories, and aliases explicitly supplied by the user. Brand aliases may map to one type; never merge changed item types.",
            "x-openai-isConsequential": True,
            "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                "code": {"type": ["string", "null"]}, "canonical_name": {"type": "string", "minLength": 1},
                "category_code": {"type": ["string", "null"]}, "base_unit": {"type": ["string", "null"]},
                "aliases": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object", "additionalProperties": True},
                "commit": {"type": "boolean", "default": False},
            }, ["canonical_name", "commit"])}}},
            "responses": {"200": {"description": "Master item preview or save result", "content": {"application/json": {"schema": save_response}}}},
        },
    }


def _calculator_plan_preview_operation() -> dict[str, Any]:
    summary_item = obj({
        "client_key": {"type": "string", "minLength": 1},
        "date": {"type": "string", "format": "date"},
        "plan_name": {"type": "string"},
        "item_hash": {"type": "string", "minLength": 8},
        "menu_count": {"type": "integer", "minimum": 0},
    }, ["client_key", "date", "item_hash"])
    existing_plan = obj({
        "documentId": {"type": "string"},
        "planName": {"type": ["string", "null"]},
        "itemHash": {"type": "string"},
    })
    preview_row = obj({
        "clientKey": {"type": "string"},
        "date": {"type": "string"},
        "planName": {"type": "string"},
        "menuCount": {"type": "integer"},
        "itemHash": {"type": "string"},
        "status": {"type": "string"},
        "selectable": {"type": "boolean"},
        "defaultSelected": {"type": "boolean"},
        "existingPlans": {"type": "array", "items": existing_plan},
    })
    response_schema = obj({
        "committed": {"type": "boolean"},
        "site": {"type": "string"},
        "sourceRef": {"type": "string"},
        "items": {"type": "array", "items": preview_row},
        "rule": {"type": "string"},
    })
    return {
        "post": {
            "operationId": "previewSppgCalculatorDailyPlanImport",
            "summary": "Preview selectable daily plans without uploading full plan payloads",
            "description": "READ-ONLY. Checks plan contents against one calculator. Distinct plans may share a date. Existing identical content and exact duplicates in the file are not selectable.",
            "x-openai-isConsequential": False,
            "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                "source_ref": {"type": "string", "minLength": 1},
                "items": {"type": "array", "maxItems": 500, "items": summary_item},
            }, ["site", "source_ref", "items"])}}},
            "responses": {"200": {"description": "Plan import preview", "content": {"application/json": {"schema": response_schema}}}},
        }
    }


def _calculator_data_import_operation() -> dict[str, Any]:
    import_item = obj({
        "client_key": {"type": "string", "minLength": 1},
        "payload": {"type": "object", "additionalProperties": True},
    }, ["client_key", "payload"])
    existing_plan = obj({
        "documentId": {"type": "string"},
        "planName": {"type": ["string", "null"]},
    })
    result_item = obj({
        "clientKey": {"type": "string"},
        "recordKey": {"type": "string"},
        "name": {"type": "string"},
        "date": {"type": "string"},
        "planName": {"type": ["string", "null"]},
        "status": {"type": "string"},
        "selectable": {"type": "boolean"},
        "defaultSelected": {"type": "boolean"},
        "sourceHash": {"type": "string"},
        "itemHash": {"type": "string"},
        "menuCount": {"type": "integer"},
        "eventId": {"type": "integer"},
        "targetPath": {"type": "string"},
        "documentId": {"type": "string"},
        "existingPlans": {"type": "array", "items": existing_plan},
        "siteStatuses": {"type": "object", "properties": {
            "MAJA": {"type": "string"}, "CEMPLANG": {"type": "string"},
        }, "additionalProperties": False},
    })
    response_schema = obj({
        "committed": {"type": "boolean"},
        "site": {"type": "string"},
        "sourceSite": {"type": "string"},
        "targetSites": {"type": "array", "items": {"type": "string"}},
        "dataType": {"type": "string"},
        "sourceRef": {"type": "string"},
        "committedCount": {"type": "integer"},
        "skippedCount": {"type": "integer"},
        "items": {"type": "array", "items": result_item},
        "skipped": {"type": "array", "items": result_item},
        "rule": {"type": "string"},
        "dailyPlansChanged": {"type": "boolean"},
    })
    return {
        "post": {
            "operationId": "previewOrImportSelectedSppgCalculatorData",
            "summary": "Preview or import selected calculator masters and daily plans",
            "description": "Use commit=false first. Master writes mirror to Maja+Cemplang; daily plans stay site-specific. Distinct plans may share a date; identical plans are skipped. CHANGED masters require selection.",
            "x-openai-isConsequential": True,
            "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                "data_type": {"type": "string", "enum": ["PRICES", "GRAMASI", "RECIPES", "BUMBU", "DAILY_PLANS"]},
                "source_ref": {"type": "string", "minLength": 1},
                "items": {"type": "array", "maxItems": 500, "items": import_item},
                "actor": {"type": "string", "default": "chatgpt"},
                "commit": {"type": "boolean", "default": False},
            }, ["site", "data_type", "source_ref", "items", "commit"])}}},
            "responses": {"200": {"description": "Calculator data preview or import result", "content": {"application/json": {"schema": response_schema}}}},
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


def schema_v0181() -> dict[str, Any]:
    payload = deepcopy(schema_v0180())
    payload["info"] = {
        "title": "SPPG Operations, Warehouse, and Accountant Bridge",
        "version": "0.18.1",
        "description": "The v0.18.0 workflow plus warehouse SO baselines, stock projections, and canonical inventory item aliases.",
    }
    payload["paths"]["/v1/inventory/stock-opname/whatsapp"] = _stock_opname_operation()
    payload["paths"]["/v1/inventory/balances"] = _projected_inventory_operation()
    payload["paths"]["/v1/inventory/items"] = _inventory_master_operation()
    return payload


def schema_v0182() -> dict[str, Any]:
    payload = deepcopy(schema_v0181())
    payload["info"] = {
        "title": "SPPG Operations, Calculator Data, Warehouse, and Accountant Bridge",
        "version": "0.18.2",
        "description": "The v0.18.1 workflow plus one-door calculator master imports, selectable daily-plan restore, and source-backed SO classification.",
    }
    payload["paths"]["/v1/calculator-data/plan-preview"] = _calculator_plan_preview_operation()
    payload["paths"]["/v1/calculator-data/import"] = _calculator_data_import_operation()
    return payload


def schema_v0183() -> dict[str, Any]:
    payload = deepcopy(schema_v0182())
    payload["info"] = {
        "title": "SPPG Operations, Calculator Data, Warehouse, and Accountant Bridge",
        "version": "0.18.3",
        "description": "The v0.18.2 workflow plus single-baseline SO enforcement and editable warehouse correction support.",
    }
    return payload


def schema_v0184() -> dict[str, Any]:
    payload = deepcopy(schema_v0183())
    payload["info"] = {
        "title": "SPPG Operations, Calculator Data, Warehouse, and Accountant Bridge",
        "version": "0.18.4",
        "description": "The v0.18.3 workflow plus multi-day purchase-order coverage in one canonical vendor message.",
    }
    stock_opname = payload["paths"]["/v1/inventory/stock-opname/whatsapp"]["post"]
    stock_opname["description"] = (
        "One WhatsApp SO is one physical stock snapshot. Preview once then commit once; Never split by area or mapping. "
        "A newer SO replaces the prior physical count, not adds to it. Keep qty 0 even without a unit; preserve raw name and mixed units."
    )
    return payload


def _application_operations_gateway() -> dict[str, Any]:
    """Compact Action surface for application screens absent from the legacy GPT.

    The backend validates each named operation against the same Pydantic model
    and domain function used by the Operations application.  The gateway is
    intentionally allow-listed so an Action cannot invoke auth/webhook routes.
    """
    read_resources = [
        "DASHBOARD", "PO_CALENDAR", "PO_REMINDERS", "VENDORS", "PLANNING_SNAPSHOTS",
        "PURCHASE_ORDERS", "GOODS_RECEIPTS", "RECEIVING_VARIANCE", "STOCK_OPNAMES", "INVENTORY_ITEM_MASTER",
        "ACTUAL_USAGE", "ACCOUNTANT_FLOW", "BGN_FLOW", "VENDOR_PAYMENTS", "AUDIT_LOG",
    ]
    write_operations = [
        "CREATE_PLANNING_SNAPSHOT", "CREATE_PURCHASE_ORDER", "EDIT_DRAFT_PURCHASE_ORDER",
        "REVISE_PURCHASE_ORDER", "CANCEL_PURCHASE_ORDER", "FINALIZE_PURCHASE_ORDER",
        "MARK_PURCHASE_ORDER_SENT", "RECORD_GOODS_RECEIPT_MANUAL", "RECORD_ACTUAL_USAGE",
        "SYNC_CALCULATOR_PLANNING", "SET_VENDOR_WHATSAPP", "SET_VENDOR_LEAD_TIME",
        "REVIEW_EVENT", "VOID_STOCK_OPNAME", "UPSERT_INVENTORY_ITEM_MASTER", "CREATE_ACCOUNTANT_SUBMISSION",
        "MARK_ACCOUNTANT_SUBMISSION_SENT", "CREATE_ACCOUNTANT_INVOICE", "CREATE_BGN_MAKER",
        "CREATE_BGN_APPROVAL", "CREATE_BGN_RECEIPT", "CREATE_SETTLEMENT",
    ]
    read_schema = obj({
        "resource": {"type": "string", "enum": read_resources},
        "site": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"], "format": "date"},
        "from_date": {"type": ["string", "null"], "format": "date"},
        "to_date": {"type": ["string", "null"], "format": "date"},
        "vendor": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"], "enum": ["KOPERASI", "MAJA", "CEMPLANG", None]},
        "search": {"type": ["string", "null"]},
        "record_id": {"type": ["integer", "null"], "minimum": 1},
        "production_cycle_id": {"type": ["integer", "null"], "minimum": 1},
        "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
        "horizon_days": {"type": ["integer", "null"], "minimum": 1, "maximum": 31},
    }, ["resource"])
    read_response = obj({
        "resource": {"type": "string"},
        "result": {"type": "object", "properties": {}, "additionalProperties": True},
    }, ["resource", "result"])
    write_schema = obj({
        "operation": {"type": "string", "enum": write_operations},
        "payload": {"type": "object", "properties": {}, "additionalProperties": True},
        "commit": {"type": "boolean", "default": False},
    }, ["operation", "payload", "commit"])
    write_response = obj({
        "committed": {"type": "boolean"},
        "canCommit": {"type": ["boolean", "null"]},
        "operation": {"type": "string"},
        "normalizedPayload": {"type": "object", "properties": {}, "additionalProperties": True},
        "result": {"type": "object", "properties": {}, "additionalProperties": True},
        "message": {"type": ["string", "null"]},
    }, ["committed", "operation"])
    return {
        "/v1/gpt/operations/read": {
            "post": {
                "operationId": "readSppgOperationalApplication",
                "summary": "Read an operational application workspace through GPT",
                "description": "READ-ONLY. Use this for the Operations dashboard, planning, POs, receipts, stock-opname history, flows, vendor/payment lists, and audit log. Select only the needed resource and filters.",
                "x-openai-isConsequential": False,
                "requestBody": {"required": True, "content": {"application/json": {"schema": read_schema}}},
                "responses": {"200": {"description": "Operational application data", "content": {"application/json": {"schema": read_response}}}},
            }
        },
        "/v1/gpt/operations/execute": {
            "post": {
                "operationId": "previewOrExecuteSppgOperationalApplication",
                "summary": "Preview or send an approved operational command to the application",
                "description": "Use commit=false first. With commit=true, validates and runs the named allow-listed application operation using the same backend workflow as the Operations screen. Never use for login, webhooks, or arbitrary routes.",
                "x-openai-isConsequential": True,
                "requestBody": {"required": True, "content": {"application/json": {"schema": write_schema}}},
                "responses": {"200": {"description": "Preview or committed application operation", "content": {"application/json": {"schema": write_response}}}},
            }
        },
    }


def schema_v0185() -> dict[str, Any]:
    payload = deepcopy(schema_v0184())
    payload["info"] = {
        "title": "SPPG Full Operations Application Bridge",
        "version": "0.18.5",
        "description": "The v0.18.4 SPPG workflow plus an allow-listed bridge for all operational application screens and commands not previously exposed to GPT.",
    }
    payload["paths"].update(_application_operations_gateway())
    return payload


def schema_v0186() -> dict[str, Any]:
    """Thirty-operation GPT schema without duplicated item-master actions."""
    payload = deepcopy(schema_v0185())
    payload["info"] = {
        "title": "SPPG Full Operations Application Bridge",
        "version": "0.18.6",
        "description": "Thirty-operation SPPG schema. Use the allow-listed application bridge for full operational reads and commands, including the inventory item master.",
    }
    payload["paths"].pop("/v1/inventory/items", None)
    # Finance Admin is an operator-owned GPT. Expose ChatGPT's "Always allow"
    # choice for every Action instead of forcing confirmation on each call.
    for methods in payload["paths"].values():
        for operation in methods.values():
            if isinstance(operation, dict) and "operationId" in operation:
                operation["x-openai-isConsequential"] = False
    return payload


@router.get("/schema/chatgpt-sppg-v0180.json", include_in_schema=False)
def chatgpt_sppg_schema_v0180() -> JSONResponse:
    return JSONResponse(schema_v0180())


@router.get("/schema/chatgpt-sppg-v0181.json", include_in_schema=False)
def chatgpt_sppg_schema_v0181() -> JSONResponse:
    return JSONResponse(schema_v0181())


@router.get("/schema/chatgpt-sppg-v0182.json", include_in_schema=False)
def chatgpt_sppg_schema_v0182() -> JSONResponse:
    return JSONResponse(schema_v0182())


@router.get("/schema/chatgpt-sppg-v0183.json", include_in_schema=False)
def chatgpt_sppg_schema_v0183() -> JSONResponse:
    return JSONResponse(schema_v0183())


@router.get("/schema/chatgpt-sppg-v0184.json", include_in_schema=False)
def chatgpt_sppg_schema_v0184() -> JSONResponse:
    return JSONResponse(schema_v0184())


@router.get("/schema/chatgpt-sppg-v0180.json", include_in_schema=False)
def chatgpt_sppg_schema_v0180() -> JSONResponse:
    return JSONResponse(schema_v0180())


@router.get("/schema/chatgpt-sppg-v0181.json", include_in_schema=False)
def chatgpt_sppg_schema_v0181() -> JSONResponse:
    return JSONResponse(schema_v0181())


@router.get("/schema/chatgpt-sppg-v0182.json", include_in_schema=False)
def chatgpt_sppg_schema_v0182() -> JSONResponse:
    return JSONResponse(schema_v0182())


@router.get("/schema/chatgpt-sppg-v0183.json", include_in_schema=False)
def chatgpt_sppg_schema_v0183() -> JSONResponse:
    return JSONResponse(schema_v0183())


@router.get("/schema/chatgpt-sppg-v0184.json", include_in_schema=False)
def chatgpt_sppg_schema_v0184() -> JSONResponse:
    return JSONResponse(schema_v0184())


@router.get("/schema/chatgpt-sppg-v0185.json", include_in_schema=False)
def chatgpt_sppg_schema_v0185() -> JSONResponse:
    return JSONResponse(schema_v0185())


@router.get("/schema/chatgpt-sppg-v0186.json", include_in_schema=False)
def chatgpt_sppg_schema_v0186() -> JSONResponse:
    return JSONResponse(schema_v0186())
