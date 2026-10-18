"""Exceptional vendor payable without a PO/receipt.

This intentionally does NOT fabricate a purchase order, receipt, warehouse
movement, or finance transaction. It is a separate verified-bill workflow.
It can be committed only through the MCP approval service, not by a
model-controlled generic tool.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.db import connection, database_ready


MONEY = Decimal("0.01")
QTY = Decimal("0.0001")


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _qty(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(QTY, rounding=ROUND_HALF_UP)


class ManualPayableLine(BaseModel):
    item_name: str = Field(min_length=1, max_length=240)
    invoiced_qty: Decimal = Field(gt=0)
    unit: str | None = Field(default=None, max_length=40)
    vendor_cost_price: Decimal = Field(ge=0)
    rejected_qty: Decimal = Field(default=Decimal(0), ge=0)
    item_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_qty(self):
        if self.rejected_qty > self.invoiced_qty:
            raise ValueError("rejected_qty cannot exceed invoiced_qty")
        return self


class ManualPayableIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    vendor_code: str = Field(min_length=1, max_length=100)
    invoice_number: str | None = Field(default=None, max_length=160)
    invoice_date: date
    due_date: date | None = None
    source_ref: str | None = Field(default=None, max_length=240)
    source_type: Literal["WHATSAPP_PRIVATE", "WHATSAPP_GROUP", "PAPER_INVOICE", "OTHER"] = "WHATSAPP_PRIVATE"
    evidence_uri: str | None = Field(default=None, max_length=1500)
    exception_reason: str = Field(min_length=10, max_length=1500)
    lines: list[ManualPayableLine] = Field(min_length=1, max_length=150)
    declared_total: Decimal | None = Field(default=None, ge=0)
    commit: bool = False

    @model_validator(mode="after")
    def require_reference(self):
        if not (self.invoice_number or "").strip() and not (self.source_ref or "").strip():
            raise ValueError("Invoice number or stable source_ref is mandatory for no-PO payable")
        return self


def _identity(payload: ManualPayableIn) -> dict[str, Any]:
    return {
        "site": payload.site,
        "vendor": payload.vendor_code.upper().strip(),
        "invoice_number": (payload.invoice_number or "").strip().upper(),
        "invoice_date": payload.invoice_date.isoformat(),
        "source_ref": (payload.source_ref or "").strip().upper(),
        "lines": [
            {
                "item_name": " ".join(line.item_name.casefold().split()),
                "quantity": str(_qty(line.invoiced_qty)),
                "rejected": str(_qty(line.rejected_qty)),
                "price": str(_money(line.vendor_cost_price)),
                "unit": (line.unit or "").strip().lower(),
            }
            for line in payload.lines
        ],
    }


def _fingerprint(payload: ManualPayableIn) -> str:
    encoded = json.dumps(_identity(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "no-po-payable:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_manual_payable(payload: ManualPayableIn) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for line in payload.lines:
        gross = _money(line.invoiced_qty * line.vendor_cost_price)
        rejected = _money(line.rejected_qty * line.vendor_cost_price)
        net = gross - rejected
        rows.append({
            "itemName": line.item_name.strip(),
            "itemCode": line.item_code,
            "invoicedQty": str(_qty(line.invoiced_qty)),
            "rejectedQty": str(_qty(line.rejected_qty)),
            "payableQty": str(_qty(line.invoiced_qty - line.rejected_qty)),
            "unit": (line.unit or "").strip() or None,
            "unitPrice": str(_money(line.vendor_cost_price)),
            "grossAmount": str(gross),
            "rejectDeduction": str(rejected),
            "netAmount": str(net),
        })

    gross_amount = sum((Decimal(r["grossAmount"]) for r in rows), Decimal(0))
    reject_amount = sum((Decimal(r["rejectDeduction"]) for r in rows), Decimal(0))
    net_amount = gross_amount - reject_amount
    warnings = [
        "TAGIHAN TANPA PO: bukan bukti barang diterima; tidak menambah stok.",
        "Membuat payable saja; tidak membuat pembayaran atau transaksi Akuntan.",
        "Pastikan tidak ada PO/receipt/invoice lama untuk bukti yang sama.",
    ]
    if net_amount <= 0:
        warnings.append("Nilai netto nol; tidak ada hutang positif untuk dibuat.")
    if payload.declared_total is not None and abs(net_amount - _money(payload.declared_total)) > MONEY:
        warnings.append(
            f"TOTAL BERBEDA: tertulis {_money(payload.declared_total)}, dihitung {net_amount}."
        )
    return {
        "committed": False,
        "canCommit": net_amount > 0 and not (
            payload.declared_total is not None
            and abs(net_amount - _money(payload.declared_total)) > MONEY
        ),
        "sourceKey": _fingerprint(payload),
        "site": payload.site,
        "vendorCode": payload.vendor_code.upper().strip(),
        "invoiceNumber": payload.invoice_number,
        "invoiceDate": payload.invoice_date.isoformat(),
        "sourceType": payload.source_type,
        "sourceRef": payload.source_ref,
        "exceptionReason": payload.exception_reason,
        "purchaseOrderId": None,
        "goodsReceiptId": None,
        "noPoException": True,
        "grossAmount": str(gross_amount),
        "rejectDeduction": str(reject_amount),
        "netAmount": str(net_amount),
        "declaredTotal": str(_money(payload.declared_total)) if payload.declared_total is not None else None,
        "lines": rows,
        "warnings": warnings,
        "stockMovementCreated": False,
        "financeTransactionCreated": False,
    }


def commit_manual_payable(payload: ManualPayableIn) -> dict[str, Any]:
    """Internal dispatcher only. Caller MUST enforce server-side approval ticket."""
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    preview = preview_manual_payable(payload)
    if not preview["canCommit"]:
        raise HTTPException(409, "Manual payable is not safe to commit")
    invoice_no = (payload.invoice_number or "").strip() or None
    vendor = payload.vendor_code.strip().upper()
    key = preview["sourceKey"]

    with connection() as conn:
        with conn.cursor() as cur:
            # Serializes attempts for identical human invoice identity.
            scope = f"{payload.site}|{vendor}|{(invoice_no or payload.source_ref or '').strip().upper()}"
            cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (scope,))
            cur.execute(
                "select id,payable_status,net_amount from vendor_invoices where source_key=%s",
                (key,),
            )
            duplicate = cur.fetchone()
            if duplicate:
                return {
                    **preview,
                    "committed": True,
                    "duplicate": True,
                    "vendorInvoiceId": duplicate["id"],
                    "payableStatus": duplicate["payable_status"],
                }

            if invoice_no:
                cur.execute(
                    """select id,source_key,net_amount,payable_status from vendor_invoices
                       where upper(site)=%s and upper(vendor_code)=%s
                         and upper(trim(coalesce(invoice_number,'')))=%s
                         and coalesce(payable_status,'UNPAID') not in ('CANCELLED','CANCELED')
                       order by id desc limit 5""",
                    (payload.site, vendor, invoice_no.upper()),
                )
                if cur.fetchall():
                    raise HTTPException(
                        409, "Invoice number already exists for this site/vendor; review and correct existing payable instead"
                    )
            elif payload.source_ref:
                cur.execute(
                    """select id from vendor_invoices where site=%s and upper(vendor_code)=%s
                       and source_key like 'no-po-payable:%' and invoice_date=%s
                       and net_amount=%s order by id desc limit 5""",
                    (payload.site, vendor, payload.invoice_date, preview["netAmount"]),
                )
                if cur.fetchall():
                    raise HTTPException(
                        409, "Potential no-invoice-number duplicate at same site/vendor/date/amount; reconcile manually"
                    )

            cur.execute(
                """insert into vendor_invoices(
                     vendor_code,site,invoice_number,invoice_date,gross_amount,
                     reject_deduction,net_amount,evidence_uri,payable_status,due_date,source_key
                   ) values (%s,%s,%s,%s,%s,%s,%s,%s,'UNPAID',%s,%s) returning id""",
                (
                    vendor, payload.site, invoice_no, payload.invoice_date,
                    preview["grossAmount"], preview["rejectDeduction"], preview["netAmount"],
                    payload.evidence_uri, payload.due_date, key,
                ),
            )
            invoice_id = int(cur.fetchone()["id"])
            for line in preview["lines"]:
                cur.execute(
                    """insert into vendor_invoice_items(
                         vendor_invoice_id,item_code,item_name,invoiced_qty,unit,vendor_cost_price,
                         line_total,rejected_qty,payable_qty,reject_amount
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        invoice_id, line["itemCode"], line["itemName"], line["invoicedQty"], line["unit"],
                        line["unitPrice"], line["netAmount"], line["rejectedQty"],
                        line["payableQty"], line["rejectDeduction"],
                    ),
                )
            conn.commit()
            return {
                **preview,
                "committed": True,
                "duplicate": False,
                "vendorInvoiceId": invoice_id,
                "payableStatus": "UNPAID",
            }
