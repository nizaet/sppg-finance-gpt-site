from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["chatgpt-schema"])

SERVER = "https://sppg-finance-gpt-site-production-5b7d.up.railway.app"


def obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties}


def arr(item_schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item_schema}


def schema() -> dict[str, Any]:
    po_item = obj({
        "purchase_order_item_id": {"type": "integer"},
        "item_code": {"type": ["string", "null"]},
        "item_name": {"type": "string"},
        "planned_qty": {"type": ["number", "null"]},
        "po_qty": {"type": ["number", "null"]},
        "unit": {"type": ["string", "null"]},
        "planning_price": {"type": ["number", "null"]},
        "po_price": {"type": ["number", "null"]},
    })
    po_record = obj({
        "purchase_order_id": {"type": "integer"},
        "po_code": {"type": "string"},
        "revision_no": {"type": "integer"},
        "site": {"type": "string"},
        "vendor_code": {"type": "string"},
        "status": {"type": "string"},
        "distribution_date": {"type": ["string", "null"], "format": "date"},
        "item_count": {"type": "integer"},
        "items": arr(po_item),
    })
    receipt_item = obj({
        "goods_receipt_item_id": {"type": "integer"},
        "purchase_order_item_id": {"type": ["integer", "null"]},
        "item_name": {"type": ["string", "null"]},
        "reported_item_name": {"type": ["string", "null"]},
        "po_qty_snapshot": {"type": ["number", "null"]},
        "received_qty": {"type": ["number", "null"]},
        "rejected_qty": {"type": ["number", "null"]},
        "accepted_qty": {"type": ["number", "null"]},
        "variance_qty": {"type": ["number", "null"]},
        "unit": {"type": ["string", "null"]},
        "planned_qty": {"type": ["number", "null"]},
        "po_qty": {"type": ["number", "null"]},
        "planning_price": {"type": ["number", "null"]},
        "po_price": {"type": ["number", "null"]},
    })
    receipt_record = obj({
        "goods_receipt_id": {"type": "integer"},
        "purchase_order_id": {"type": "integer"},
        "po_code": {"type": "string"},
        "site": {"type": "string"},
        "vendor_code": {"type": "string"},
        "received_at": {"type": ["string", "null"], "format": "date-time"},
        "distribution_date": {"type": ["string", "null"], "format": "date"},
        "match_status": {"type": ["string", "null"]},
        "items": arr(receipt_item),
    })
    parsed_line = obj({
        "reported_item_name": {"type": "string"},
        "item_name": {"type": "string"},
        "invoiced_qty": {"type": "number"},
        "unit": {"type": "string"},
        "vendor_cost_price": {"type": "number"},
        "computed_line_total": {"type": "number"},
        "rejected_qty": {"type": "number"},
        "reject_amount": {"type": "number"},
        "payable_qty": {"type": "number"},
        "net_line_total": {"type": "number"},
    })
    payable_line = obj({
        "goods_receipt_item_id": {"type": "integer"},
        "purchase_order_item_id": {"type": ["integer", "null"]},
        "item_name": {"type": "string"},
        "accepted_qty": {"type": "number"},
        "invoiced_qty": {"type": "number"},
        "rejected_qty": {"type": "number"},
        "payable_qty": {"type": "number"},
        "unit": {"type": ["string", "null"]},
        "po_qty": {"type": ["number", "null"]},
        "vendor_cost_price": {"type": "number"},
        "gross_line_total": {"type": "number"},
        "reject_amount": {"type": "number"},
        "line_total": {"type": "number"},
        "invoice_vs_po_variance": {"type": ["number", "null"]},
        "invoice_vs_receipt_variance": {"type": "number"},
    })
    generic_stock_item = obj({
        "itemName": {"type": "string"},
        "qty": {"type": "number"},
        "unit": {"type": ["string", "null"]},
        "fromLocation": {"type": ["string", "null"]},
        "toLocation": {"type": ["string", "null"]},
    })

    paths: dict[str, Any] = {
        "/v1/vendor-invoices/parse-whatsapp": {
            "post": {
                "operationId": "parseOnlySuppliedSppgVendorInvoiceText",
                "summary": "Parse only vendor invoice text supplied by user",
                "description": "READ-ONLY. Parse only the exact invoice text supplied in the current request. Do not substitute PO, finance, history, or other database data. Do not invent missing prices.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                    "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                    "vendor_code": {"type": "string"},
                    "invoice_date_label": {"type": "string"},
                    "text": {"type": "string", "minLength": 1},
                })}}},
                "responses": {"200": {"description": "Parsed invoice", "content": {"application/json": {"schema": obj({
                    "vendorCode": {"type": ["string", "null"]}, "site": {"type": ["string", "null"]},
                    "declaredTotal": {"type": ["number", "null"]}, "grossAmount": {"type": "number"},
                    "rejectDeduction": {"type": "number"}, "netAmount": {"type": "number"},
                    "canCommit": {"type": "boolean"}, "financeTransactionCreated": {"type": "boolean"},
                    "paymentDraft": {"type": "string"}, "warnings": arr({"type": "string"}), "items": arr(parsed_line),
                })}}}},
            }
        },
        "/v1/purchase-orders/search": {
            "get": {
                "operationId": "searchSppgPurchaseOrdersForReconciliation",
                "summary": "Search existing purchase orders",
                "description": "READ-ONLY. Use before payable reconciliation to find the real PO. Never invent a purchase_order_id.",
                "parameters": [
                    {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                    {"in": "query", "name": "vendor", "schema": {"type": "string"}},
                    {"in": "query", "name": "poCode", "schema": {"type": "string"}},
                    {"in": "query", "name": "distributionDate", "schema": {"type": "string", "format": "date"}},
                    {"in": "query", "name": "status", "schema": {"type": "string"}},
                    {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
                ],
                "responses": {"200": {"description": "Matching POs", "content": {"application/json": {"schema": obj({"items": arr(po_record), "count": {"type": "integer"}})}}}},
            }
        },
        "/v1/goods-receipts/search": {
            "get": {
                "operationId": "searchSppgGoodsReceiptsForReconciliation",
                "summary": "Search existing goods receipts",
                "description": "READ-ONLY. Find the actual goods receipt before payable reconciliation. Never invent a goods_receipt_id.",
                "parameters": [
                    {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                    {"in": "query", "name": "vendor", "schema": {"type": "string"}},
                    {"in": "query", "name": "purchaseOrderId", "schema": {"type": "integer"}},
                    {"in": "query", "name": "distributionDate", "schema": {"type": "string", "format": "date"}},
                    {"in": "query", "name": "receivedDate", "schema": {"type": "string", "format": "date"}},
                    {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
                ],
                "responses": {"200": {"description": "Matching goods receipts", "content": {"application/json": {"schema": obj({"items": arr(receipt_record), "count": {"type": "integer"}})}}}},
            }
        },
        "/v1/vendor-payables/from-receipt": {
            "post": {
                "operationId": "processSppgVendorPayableFromReceipt",
                "summary": "Preview or commit reconciled vendor payable",
                "description": "Use only after real PO and goods receipt are found. Always preview with commit=false. Keep PO, received, invoice, reject, and payable quantities separate.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                    "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]},
                    "purchase_order_id": {"type": "integer"}, "goods_receipt_id": {"type": "integer"},
                    "invoice_number": {"type": ["string", "null"]}, "invoice_date": {"type": ["string", "null"], "format": "date"},
                    "due_date": {"type": ["string", "null"], "format": "date"}, "evidence_uri": {"type": ["string", "null"]},
                    "commit": {"type": "boolean", "default": False},
                    "lines": arr(obj({
                        "goods_receipt_item_id": {"type": ["integer", "null"]}, "item_name": {"type": ["string", "null"]},
                        "vendor_cost_price": {"type": "number", "minimum": 0}, "invoiced_qty": {"type": ["number", "null"], "minimum": 0},
                        "rejected_qty": {"type": "number", "minimum": 0, "default": 0},
                    })),
                })}}},
                "responses": {"200": {"description": "Payable preview or commit", "content": {"application/json": {"schema": obj({
                    "committed": {"type": "boolean"}, "canCommit": {"type": "boolean"}, "duplicate": {"type": ["boolean", "null"]},
                    "vendorInvoiceId": {"type": ["integer", "null"]}, "site": {"type": "string"}, "purchaseOrderId": {"type": "integer"},
                    "poCode": {"type": "string"}, "goodsReceiptId": {"type": "integer"}, "vendorCode": {"type": "string"},
                    "payableStatus": {"type": "string"}, "grossAmount": {"type": "number"}, "rejectDeduction": {"type": "number"},
                    "netAmount": {"type": "number"}, "financeTransactionCreated": {"type": "boolean"},
                    "warnings": arr({"type": "string"}), "lines": arr(payable_line),
                })}}}},
            }
        },
        "/v1/vendor-payables": {
            "get": {
                "operationId": "searchSppgVendorPayables",
                "summary": "Search recorded vendor payables",
                "parameters": [
                    {"in": "query", "name": "site", "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                    {"in": "query", "name": "vendor", "schema": {"type": "string"}},
                    {"in": "query", "name": "status", "schema": {"type": "string"}},
                    {"in": "query", "name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200}},
                ],
                "responses": {"200": {"description": "Matching payables", "content": {"application/json": {"schema": obj({"items": arr(obj({
                    "vendor_invoice_id": {"type": "integer"}, "vendor_code": {"type": "string"}, "site": {"type": "string"},
                    "purchase_order_id": {"type": ["integer", "null"]}, "goods_receipt_id": {"type": ["integer", "null"]},
                    "invoice_number": {"type": ["string", "null"]}, "gross_amount": {"type": "number"},
                    "reject_deduction": {"type": "number"}, "net_amount": {"type": "number"}, "payable_status": {"type": "string"},
                }))})}}}},
            }
        },
        "/v1/vendor-payments/confirm": {
            "post": {
                "operationId": "confirmSppgVendorPayment",
                "summary": "Preview or confirm vendor payment evidence",
                "description": "Use commit=false first. Commit only after explicit payment evidence. Does not automatically create a finance transaction.",
                "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                    "vendor_invoice_id": {"type": "integer"}, "amount": {"type": "number", "exclusiveMinimum": 0},
                    "paid_at": {"type": ["string", "null"], "format": "date-time"}, "payment_source": {"type": ["string", "null"]},
                    "reference_number": {"type": ["string", "null"]}, "evidence_uri": {"type": ["string", "null"]},
                    "source_external_id": {"type": ["string", "null"]}, "commit": {"type": "boolean", "default": False},
                })}}},
                "responses": {"200": {"description": "Payment preview or commit", "content": {"application/json": {"schema": obj({
                    "committed": {"type": "boolean"}, "duplicate": {"type": ["boolean", "null"]}, "vendorPaymentId": {"type": ["integer", "null"]},
                    "vendorInvoiceId": {"type": "integer"}, "vendorCode": {"type": "string"}, "site": {"type": "string"},
                    "netAmount": {"type": "number"}, "alreadyPaid": {"type": "number"}, "paymentAmount": {"type": "number"},
                    "remainingBefore": {"type": "number"}, "remainingAfter": {"type": "number"}, "payableStatusAfter": {"type": "string"},
                    "canCommit": {"type": "boolean"}, "financeTransactionCreated": {"type": "boolean"},
                })}}}},
            }
        },
        "/v1/inventory/from-receipt": {
            "post": {
                "operationId": "postSppgReceiptToInventory",
                "summary": "Preview or post receipt into stock",
                "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                    "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}, "goods_receipt_id": {"type": "integer"}, "commit": {"type": "boolean", "default": False}
                })}}},
                "responses": {"200": {"description": "Stock receipt result", "content": {"application/json": {"schema": obj({
                    "committed": {"type": "boolean"}, "canCommit": {"type": ["boolean", "null"]}, "goodsReceiptId": {"type": "integer"},
                    "inserted": {"type": ["integer", "null"]}, "duplicates": {"type": ["integer", "null"]}, "items": arr(generic_stock_item),
                })}}}},
            }
        },
        "/v1/inventory/usage": {
            "post": {
                "operationId": "processSppgInventoryUsage",
                "summary": "Preview or record actual stock usage",
                "requestBody": {"required": True, "content": {"application/json": {"schema": obj({
                    "site": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}, "item_name": {"type": "string"},
                    "qty": {"type": "number", "exclusiveMinimum": 0}, "unit": {"type": "string"},
                    "source_ref": {"type": ["string", "null"]}, "commit": {"type": "boolean", "default": False},
                })}}},
                "responses": {"200": {"description": "Usage result", "content": {"application/json": {"schema": obj({
                    "committed": {"type": "boolean"}, "duplicate": {"type": ["boolean", "null"]}, "movementId": {"type": ["integer", "null"]},
                    "site": {"type": "string"}, "itemName": {"type": "string"}, "balanceBefore": {"type": "number"},
                    "usageQty": {"type": "number"}, "balanceAfter": {"type": "number"}, "unit": {"type": "string"}, "stockWarning": {"type": "boolean"},
                })}}}},
            }
        },
        "/v1/inventory/balance": {
            "get": {
                "operationId": "getSppgInventoryBalance",
                "summary": "Read current stock balance",
                "parameters": [
                    {"in": "query", "name": "site", "required": True, "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                    {"in": "query", "name": "item", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "Current stock", "content": {"application/json": {"schema": obj({
                    "site": {"type": "string"}, "itemName": {"type": "string"}, "balance": {"type": "number"}
                })}}}},
            }
        },
        "/v1/inventory/requirement-preview": {
            "get": {
                "operationId": "previewSppgInventoryRequirement",
                "summary": "Preview purchase requirement after stock",
                "parameters": [
                    {"in": "query", "name": "site", "required": True, "schema": {"type": "string", "enum": ["MAJA", "CEMPLANG"]}},
                    {"in": "query", "name": "item", "required": True, "schema": {"type": "string"}},
                    {"in": "query", "name": "plannedQty", "required": True, "schema": {"type": "number", "minimum": 0}},
                    {"in": "query", "name": "unit", "schema": {"type": "string", "default": "kg"}},
                ],
                "responses": {"200": {"description": "Requirement preview", "content": {"application/json": {"schema": obj({
                    "site": {"type": "string"}, "itemName": {"type": "string"}, "plannedQty": {"type": "number"},
                    "stockAvailable": {"type": "number"}, "purchaseNeeded": {"type": "number"}, "unit": {"type": "string"},
                    "financeTransactionCreated": {"type": "boolean"},
                })}}}},
            }
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "SPPG Vendor and Inventory Operations", "version": "0.16.3", "description": "Operational vendor reconciliation, stock, invoice parsing, and payment workflow for MAJA and CEMPLANG."},
        "servers": [{"url": SERVER}],
        "security": [{"bearerAuth": []}],
        "paths": paths,
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
    }


@router.get("/schema/chatgpt-operations-v0163.json", include_in_schema=False)
def chatgpt_operations_schema_v0163() -> JSONResponse:
    return JSONResponse(schema())
