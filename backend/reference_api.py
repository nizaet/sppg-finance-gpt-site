from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.db import connection, database_ready
from backend.vendor_payables_api import router as vendor_payables_router

router = APIRouter(prefix="/v1", tags=["reference"])
router.include_router(vendor_payables_router)


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _json_response(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "200": {
            "description": "Successful response",
            "content": {"application/json": {"schema": schema}},
        }
    }


def _chatgpt_operations_v0162() -> dict[str, Any]:
    invoice_line = _obj({
        "reported_item_name": {"type": "string"},
        "item_name": {"type": "string"},
        "invoiced_qty": {"type": "number"},
        "unit": {"type": "string"},
        "vendor_cost_price": {"type": "number"},
        "declared_line_total": {"type": "number"},
        "computed_line_total": {"type": "number"},
        "line_total_matches": {"type": "boolean"},
        "rejected_qty": {"type": "number"},
        "reject_amount": {"type": "number"},
        "payable_qty": {"type": "number"},
        "net_line_total": {"type": "number"},
        "reject_match_confidence": {"type": "number"},
    })
    payable_line = _obj({
        "goods_receipt_item_id": {"type": ["integer", "null"]},
        "purchase_order_item_id": {"type": ["integer", "null"]},
        "item_name": {"type": "string"},
        "accepted_qty": {"type": "number"},
        "invoiced_qty": {"type": "number"},
        "rejected_qty": {"type": "number"},
        "payable_qty": {"type": "number"},
        "unit": {"type": ["string", "null"]},
        "planned_qty": {"type": ["number", "null"]},
        "po_qty": {"type": ["number", "null"]},
        "planning_price": {"type": ["number", "null"]},
        "po_price": {"type": ["number", "null"]},
        "vendor_cost_price": {"type": "number"},
        "gross_line_total": {"type": "number"},
        "reject_amount": {"type": "number"},
        "line_total": {"type": "number"},
        "invoice_vs_po_variance": {"type": ["number", "null"]},
        "invoice_vs_receipt_variance": {"type": "number"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    })
    payable_record = _obj({
        "vendor_invoice_id": {"type": "integer"},
        "vendor_code": {"type": "string"},
        "site": {"type": "string"},
        "purchase_order_id": {"type": ["integer", "null"]},
        "goods_receipt_id": {"type": ["integer", "null"]},
        "invoice_number": {"type": ["string", "null"]},
        "invoice_date": {"type": ["string", "null"], "format": "date"},
        "gross_amount": {"type": "number"},
        "reject_deduction": {"type": "number"},
        "net_amount": {"type": "number"},
        "payable_status": {"type": "string"},
        "due_date": {"type": ["string", "null"], "format": "date"},
    })
    stock_item = _obj({
        "sourceKey": {"type": "string"},
        "itemName": {"type": "string"},
        "qty": {"type": "number"},
        "unit": {"type": ["string", "null"]},
        "fromLocation": {"type": "string"},
        "toLocation": {"type": "string"},
    })

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SPPG Vendor and Inventory Operations",
            "version": "0.16.2",
            "description": "Parse supplied vendor invoices, reconcile payables, manage stock, and confirm vendor payments.",
        },
        "servers": [{"url": "https://sppg-finance-gpt-site-production-5b7d.up.railway.app"}],
        "paths": {
            "/v1/vendor-invoices/parse-whatsapp": {
                "post": {
                    "operationId": "parseOnlySuppliedSppgVendorInvoiceText",
                    "summary": "Parse only the vendor invoice text supplied by the user",
                    "description": "READ-ONLY. Use only the exact invoice text supplied in the current request. Do not replace it with PO, finance, history, or database data. Do not invent missing prices.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _obj({
                            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                            "vendor_code": {"type": "string"},
                            "invoice_date_label": {"type": "string"},
                            "text": {"type": "string", "minLength": 1},
                        }, ["site", "vendor_code", "invoice_date_label", "text"])}}
                    },
                    "responses": _json_response(_obj({
                        "vendorCode": {"type": ["string", "null"]},
                        "site": {"type": ["string", "null"]},
                        "declaredTotal": {"type": ["number", "null"]},
                        "grossAmount": {"type": "number"},
                        "rejectDeduction": {"type": "number"},
                        "netAmount": {"type": "number"},
                        "canCommit": {"type": "boolean"},
                        "financeTransactionCreated": {"type": "boolean"},
                        "paymentDraft": {"type": "string"},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "items": {"type": "array", "items": invoice_line},
                    })),
                }
            },
            "/v1/vendor-payables/from-receipt": {
                "post": {
                    "operationId": "processSppgVendorPayableFromReceipt",
                    "summary": "Preview or commit reconciled vendor payable",
                    "description": "Use only after PO and receiving exist. Preview with commit=false first. Keep PO, received, invoice, reject, and payable quantities separate.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _obj({
                            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                            "purchase_order_id": {"type": "integer"},
                            "goods_receipt_id": {"type": "integer"},
                            "invoice_number": {"type": ["string", "null"]},
                            "invoice_date": {"type": ["string", "null"], "format": "date"},
                            "due_date": {"type": ["string", "null"], "format": "date"},
                            "evidence_uri": {"type": ["string", "null"]},
                            "commit": {"type": "boolean", "default": False},
                            "lines": {"type": "array", "minItems": 1, "items": _obj({
                                "goods_receipt_item_id": {"type": ["integer", "null"]},
                                "item_name": {"type": ["string", "null"]},
                                "vendor_cost_price": {"type": "number", "minimum": 0},
                                "invoiced_qty": {"type": ["number", "null"], "minimum": 0},
                                "rejected_qty": {"type": "number", "minimum": 0, "default": 0},
                            }, ["vendor_cost_price"])},
                        }, ["site", "purchase_order_id", "goods_receipt_id", "commit", "lines"])}}
                    },
                    "responses": _json_response(_obj({
                        "committed": {"type": "boolean"},
                        "canCommit": {"type": "boolean"},
                        "duplicate": {"type": "boolean"},
                        "vendorInvoiceId": {"type": ["integer", "null"]},
                        "site": {"type": "string"},
                        "purchaseOrderId": {"type": "integer"},
                        "poCode": {"type": "string"},
                        "goodsReceiptId": {"type": "integer"},
                        "vendorCode": {"type": "string"},
                        "payableStatus": {"type": "string"},
                        "grossAmount": {"type": "number"},
                        "rejectDeduction": {"type": "number"},
                        "netAmount": {"type": "number"},
                        "financeTransactionCreated": {"type": "boolean"},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "lines": {"type": "array", "items": payable_line},
                    })),
                }
            },
            "/v1/vendor-payables": {
                "get": {
                    "operationId": "searchSppgVendorPayables",
                    "summary": "Search recorded vendor payables",
                    "description": "Search existing payable records only. Do not use this operation to parse newly supplied invoice text.",
                    "parameters": [
                        {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                        {"in": "query", "name": "vendor", "schema": {"type": "string"}},
                        {"in": "query", "name": "status", "schema": {"type": "string", "enum": ["UNPAID", "PARTIAL", "PAID", "CANCELLED"]}},
                        {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200}},
                    ],
                    "responses": _json_response(_obj({"items": {"type": "array", "items": payable_record}})),
                }
            },
            "/v1/vendor-payments/confirm": {
                "post": {
                    "operationId": "confirmSppgVendorPayment",
                    "summary": "Preview or confirm vendor payment",
                    "description": "Preview with commit=false first. A committed payment updates payable status. It does not automatically create a finance transaction.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _obj({
                            "vendor_invoice_id": {"type": "integer"},
                            "amount": {"type": "number", "exclusiveMinimum": 0},
                            "paid_at": {"type": ["string", "null"], "format": "date-time"},
                            "payment_source": {"type": ["string", "null"]},
                            "reference_number": {"type": ["string", "null"]},
                            "evidence_uri": {"type": ["string", "null"]},
                            "source_external_id": {"type": ["string", "null"]},
                            "commit": {"type": "boolean", "default": False},
                        }, ["vendor_invoice_id", "amount", "commit"])}}
                    },
                    "responses": _json_response(_obj({
                        "committed": {"type": "boolean"},
                        "duplicate": {"type": "boolean"},
                        "vendorPaymentId": {"type": ["integer", "null"]},
                        "vendorInvoiceId": {"type": "integer"},
                        "vendorCode": {"type": "string"},
                        "site": {"type": "string"},
                        "invoiceNumber": {"type": ["string", "null"]},
                        "netAmount": {"type": "number"},
                        "alreadyPaid": {"type": "number"},
                        "paymentAmount": {"type": "number"},
                        "remainingBefore": {"type": "number"},
                        "remainingAfter": {"type": "number"},
                        "payableStatusAfter": {"type": "string"},
                        "canCommit": {"type": "boolean"},
                        "financeTransactionCreated": {"type": "boolean"},
                    })),
                }
            },
            "/v1/inventory/from-receipt": {
                "post": {
                    "operationId": "postSppgReceiptToInventory",
                    "summary": "Preview or post confirmed receipt into stock",
                    "description": "Creates operational stock movements only. Use commit=false for preview. Does not create finance transactions.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _obj({
                            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                            "goods_receipt_id": {"type": "integer"},
                            "commit": {"type": "boolean", "default": False},
                        }, ["site", "goods_receipt_id", "commit"])}}
                    },
                    "responses": _json_response(_obj({
                        "committed": {"type": "boolean"},
                        "canCommit": {"type": "boolean"},
                        "goodsReceiptId": {"type": "integer"},
                        "inserted": {"type": "integer"},
                        "duplicates": {"type": "integer"},
                        "items": {"type": "array", "items": stock_item},
                    })),
                }
            },
            "/v1/inventory/usage": {
                "post": {
                    "operationId": "processSppgInventoryUsage",
                    "summary": "Preview or record actual stock usage",
                    "description": "Operational stock only. Preview with commit=false first. Usage reduces stock and does not create a finance transaction.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _obj({
                            "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                            "item_name": {"type": "string"},
                            "qty": {"type": "number", "exclusiveMinimum": 0},
                            "unit": {"type": "string"},
                            "occurred_at": {"type": ["string", "null"], "format": "date-time"},
                            "source_ref": {"type": ["string", "null"]},
                            "commit": {"type": "boolean", "default": False},
                        }, ["site", "item_name", "qty", "unit", "commit"])}}
                    },
                    "responses": _json_response(_obj({
                        "committed": {"type": "boolean"},
                        "duplicate": {"type": "boolean"},
                        "movementId": {"type": ["integer", "null"]},
                        "site": {"type": "string"},
                        "itemName": {"type": "string"},
                        "balanceBefore": {"type": "number"},
                        "usageQty": {"type": "number"},
                        "balanceAfter": {"type": "number"},
                        "unit": {"type": "string"},
                        "stockWarning": {"type": "boolean"},
                    })),
                }
            },
            "/v1/inventory/balance": {
                "get": {
                    "operationId": "getSppgInventoryBalance",
                    "summary": "Read current stock balance for one item",
                    "parameters": [
                        {"in": "query", "name": "site", "required": True, "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                        {"in": "query", "name": "item", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": _json_response(_obj({
                        "site": {"type": "string"},
                        "itemName": {"type": "string"},
                        "balance": {"type": "number"},
                    })),
                }
            },
            "/v1/inventory/requirement-preview": {
                "get": {
                    "operationId": "previewSppgInventoryRequirement",
                    "summary": "Calculate purchase requirement after current stock",
                    "description": "Use for multi-day items such as Wikian chicken. purchaseNeeded is planned quantity minus available stock, never below zero.",
                    "parameters": [
                        {"in": "query", "name": "site", "required": True, "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                        {"in": "query", "name": "item", "required": True, "schema": {"type": "string"}},
                        {"in": "query", "name": "plannedQty", "required": True, "schema": {"type": "number", "minimum": 0}},
                        {"in": "query", "name": "unit", "schema": {"type": "string", "default": "kg"}},
                    ],
                    "responses": _json_response(_obj({
                        "site": {"type": "string"},
                        "itemName": {"type": "string"},
                        "plannedQty": {"type": "number"},
                        "stockAvailable": {"type": "number"},
                        "purchaseNeeded": {"type": "number"},
                        "unit": {"type": "string"},
                        "financeTransactionCreated": {"type": "boolean"},
                    })),
                }
            },
        },
    }


@router.get("/schema/chatgpt-operations-v0162.json", include_in_schema=False)
def chatgpt_operations_v0162() -> JSONResponse:
    return JSONResponse(_chatgpt_operations_v0162())


@router.get("/schema-status")
def schema_status() -> dict[str, Any]:
    if not database_ready():
        return {"databaseReady": False, "schemaReady": False, "tables": []}
    required = [
        "candidate_events", "workflow_actions", "event_audit_log",
        "production_cycles", "purchase_orders", "vendor_payments",
        "sites", "entities", "vendor_rules", "schema_migrations",
    ]
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select table_name from information_schema.tables
                   where table_schema='public' and table_name = any(%s)""",
                (required,),
            )
            found = sorted(row["table_name"] for row in cur.fetchall())
    return {
        "databaseReady": True,
        "schemaReady": set(required).issubset(found),
        "tables": found,
        "missing": sorted(set(required) - set(found)),
    }


@router.get("/reference/sites")
def reference_sites() -> dict[str, Any]:
    if not database_ready():
        return {"items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select code, name, active from sites where active=true order by code")
            return {"items": cur.fetchall()}


@router.get("/reference/vendors")
def reference_vendors(site: str = "") -> dict[str, Any]:
    if not database_ready():
        return {"items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select e.code, e.name, e.entity_type, e.metadata,
                       vr.site_code, vr.category_code, vr.lead_time_days_before_cooking,
                       vr.payment_term_code, vr.payment_term_payload,
                       vr.internal_reimbursement, vr.intermediary_code,
                       vr.effective_from, vr.effective_to, vr.evidence_ref, vr.notes
                from entities e
                left join vendor_rules vr on vr.vendor_code=e.code
                  and vr.effective_from <= current_date
                  and (vr.effective_to is null or vr.effective_to >= current_date)
                where e.active=true
                  and e.entity_type in ('VENDOR','INTERNAL_ORG')
            """
            params: list[Any] = []
            if site:
                sql += " and (vr.site_code is null or upper(vr.site_code)=upper(%s))"
                params.append(site)
            sql += " order by e.name, vr.site_code, vr.category_code"
            cur.execute(sql, params)
            return {"items": cur.fetchall()}


@router.get("/po-schedule/preview")
def po_schedule_preview(
    distribution_date: date = Query(alias="distributionDate"),
    cooking_date: date | None = Query(default=None, alias="cookingDate"),
    site: str = "",
) -> dict[str, Any]:
    cook = cooking_date or (distribution_date - timedelta(days=1))
    if not database_ready():
        return {"distributionDate": distribution_date, "cookingDate": cook, "items": []}

    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select e.code as vendor_code, e.name as vendor_name,
                       vr.site_code, vr.category_code,
                       vr.lead_time_days_before_cooking,
                       vr.internal_reimbursement, vr.intermediary_code,
                       vr.notes
                from vendor_rules vr
                join entities e on e.code=vr.vendor_code
                where vr.effective_from <= %s
                  and (vr.effective_to is null or vr.effective_to >= %s)
            """
            params: list[Any] = [cook, cook]
            if site:
                sql += " and (vr.site_code is null or upper(vr.site_code)=upper(%s))"
                params.append(site)
            sql += " order by vr.lead_time_days_before_cooking desc nulls last, e.name"
            cur.execute(sql, params)
            rows = cur.fetchall()

    items = []
    for row in rows:
        lead = row["lead_time_days_before_cooking"]
        po_date = cook - timedelta(days=lead) if lead is not None else None
        items.append({**row, "po_date": po_date})
    return {
        "distributionDate": distribution_date,
        "cookingDate": cook,
        "site": site or None,
        "items": items,
    }
