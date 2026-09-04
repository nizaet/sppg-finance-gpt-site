from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready

router = APIRouter(tags=["vendor-payables"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def normalize_name(value: str) -> str:
    return " ".join((value or "").lower().strip().split())


class VendorCostLineIn(BaseModel):
    goods_receipt_item_id: int | None = None
    item_name: str | None = None
    vendor_cost_price: float = Field(ge=0)
    invoiced_qty: float | None = Field(default=None, ge=0)
    rejected_qty: float = Field(default=0, ge=0)


class VendorPayableFromReceiptIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    purchase_order_id: int
    goods_receipt_id: int
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    evidence_uri: str | None = None
    commit: bool = False
    lines: list[VendorCostLineIn] = Field(min_length=1)


class VendorPayableCorrectionIn(BaseModel):
    invoice_number: str | None = Field(default=None, max_length=180)
    invoice_date: date | None = None
    due_date: date | None = None
    gross_amount: float = Field(ge=0)
    reject_deduction: float = Field(default=0, ge=0)
    correction_note: str = Field(min_length=3, max_length=1000)


def payable_source_key(payload: VendorPayableFromReceiptIn, vendor_code: str) -> str:
    canonical = {
        "site": payload.site,
        "purchase_order_id": payload.purchase_order_id,
        "goods_receipt_id": payload.goods_receipt_id,
        "vendor_code": vendor_code,
        "invoice_number": payload.invoice_number,
        "lines": [
            {
                "goods_receipt_item_id": x.goods_receipt_item_id,
                "item_name": normalize_name(x.item_name or ""),
                "vendor_cost_price": x.vendor_cost_price,
                "invoiced_qty": x.invoiced_qty,
                "rejected_qty": x.rejected_qty,
            }
            for x in payload.lines
        ],
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return "vendor-payable:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_receipt_context(cur, payload: VendorPayableFromReceiptIn) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cur.execute(
        """select gr.id as goods_receipt_id, gr.purchase_order_id, po.po_code, po.site, po.vendor_code,
                  pc.id as production_cycle_id, pc.distribution_date
           from goods_receipts gr
           join purchase_orders po on po.id=gr.purchase_order_id
           left join production_cycles pc on pc.id=po.production_cycle_id
           where gr.id=%s and po.id=%s""",
        (payload.goods_receipt_id, payload.purchase_order_id),
    )
    ctx = cur.fetchone()
    if not ctx:
        raise HTTPException(404, "goods receipt or purchase order not found")
    if str(ctx["site"]).upper() != payload.site.upper():
        raise HTTPException(400, "site does not match purchase order")

    cur.execute(
        """select gri.id as goods_receipt_item_id, gri.purchase_order_item_id,
                  coalesce(gri.accepted_qty,gri.received_qty,0) as accepted_qty,
                  gri.unit, gri.reported_item_name, poi.item_code, poi.item_name,
                  poi.planned_qty, poi.po_qty, poi.planning_price, poi.po_price
           from goods_receipt_items gri
           left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
           where gri.goods_receipt_id=%s order by gri.id""",
        (payload.goods_receipt_id,),
    )
    return ctx, cur.fetchall()


def resolve_lines(payload: VendorPayableFromReceiptIn, receipt_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    used: set[int] = set()
    for requested in payload.lines:
        candidates = receipt_items
        if requested.goods_receipt_item_id is not None:
            candidates = [x for x in receipt_items if x["goods_receipt_item_id"] == requested.goods_receipt_item_id]
        elif requested.item_name:
            needle = normalize_name(requested.item_name)
            candidates = [
                x for x in receipt_items
                if normalize_name(str(x.get("item_name") or x.get("reported_item_name") or "")) == needle
                or normalize_name(str(x.get("reported_item_name") or "")) == needle
            ]
        else:
            raise HTTPException(400, "each line requires goods_receipt_item_id or item_name")

        candidates = [x for x in candidates if x["goods_receipt_item_id"] not in used]
        if len(candidates) != 1:
            raise HTTPException(409, "vendor cost line does not resolve to exactly one receipt item")
        item = candidates[0]
        used.add(item["goods_receipt_item_id"])

        accepted_qty = float(item["accepted_qty"] or 0)
        po_qty = float(item["po_qty"]) if item.get("po_qty") is not None else None
        invoiced_qty = float(requested.invoiced_qty) if requested.invoiced_qty is not None else accepted_qty
        rejected_qty = float(requested.rejected_qty or 0)
        if rejected_qty > invoiced_qty:
            raise HTTPException(400, "rejected_qty cannot exceed invoiced_qty")
        payable_qty = round(invoiced_qty - rejected_qty, 4)
        price = float(requested.vendor_cost_price)
        gross_line_total = round(invoiced_qty * price, 2)
        reject_amount = round(rejected_qty * price, 2)
        line_total = round(payable_qty * price, 2)

        warnings: list[str] = []
        if po_qty is not None and abs(invoiced_qty - po_qty) > 0.0001:
            warnings.append(f"invoice_qty differs from po_qty by {round(invoiced_qty - po_qty, 4):g}")
        if abs(invoiced_qty - accepted_qty) > 0.0001:
            warnings.append(f"invoice_qty differs from received/accepted qty by {round(invoiced_qty - accepted_qty, 4):g}")
        if rejected_qty > 0:
            warnings.append(f"reject deduction {rejected_qty:g} {item.get('unit') or ''}".strip())

        resolved.append({
            "goods_receipt_item_id": item["goods_receipt_item_id"],
            "purchase_order_item_id": item["purchase_order_item_id"],
            "item_code": item.get("item_code"),
            "item_name": item.get("item_name") or item.get("reported_item_name"),
            "accepted_qty": accepted_qty,
            "invoiced_qty": invoiced_qty,
            "rejected_qty": rejected_qty,
            "payable_qty": payable_qty,
            "unit": item.get("unit"),
            "planned_qty": float(item["planned_qty"]) if item.get("planned_qty") is not None else None,
            "po_qty": po_qty,
            "planning_price": float(item["planning_price"]) if item.get("planning_price") is not None else None,
            "po_price": float(item["po_price"]) if item.get("po_price") is not None else None,
            "vendor_cost_price": price,
            "gross_line_total": gross_line_total,
            "reject_amount": reject_amount,
            "line_total": line_total,
            "invoice_vs_po_variance": round(invoiced_qty - po_qty, 4) if po_qty is not None else None,
            "invoice_vs_receipt_variance": round(invoiced_qty - accepted_qty, 4),
            "warnings": warnings,
        })
    return resolved


@router.post("/vendor-payables/from-receipt")
def vendor_payable_from_receipt(payload: VendorPayableFromReceiptIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            ctx, receipt_items = load_receipt_context(cur, payload)
            resolved = resolve_lines(payload, receipt_items)
            gross_amount = round(sum(x["gross_line_total"] for x in resolved), 2)
            reject_deduction = round(sum(x["reject_amount"] for x in resolved), 2)
            net_amount = round(sum(x["line_total"] for x in resolved), 2)
            warnings = [w for line in resolved for w in line["warnings"]]
            source_key = payable_source_key(payload, str(ctx["vendor_code"]))
            result = {
                "committed": False,
                "canCommit": bool(resolved),
                "site": ctx["site"],
                "purchaseOrderId": ctx["purchase_order_id"],
                "poCode": ctx["po_code"],
                "goodsReceiptId": ctx["goods_receipt_id"],
                "vendorCode": ctx["vendor_code"],
                "invoiceNumber": payload.invoice_number,
                "invoiceDate": payload.invoice_date,
                "dueDate": payload.due_date,
                "payableStatus": "UNPAID",
                "grossAmount": gross_amount,
                "rejectDeduction": reject_deduction,
                "netAmount": net_amount,
                "lines": resolved,
                "warnings": warnings,
                "financeTransactionCreated": False,
            }
            if not payload.commit:
                return result

            cur.execute("select id,payable_status,net_amount from vendor_invoices where source_key=%s", (source_key,))
            duplicate = cur.fetchone()
            if duplicate:
                result.update({
                    "committed": True,
                    "duplicate": True,
                    "vendorInvoiceId": duplicate["id"],
                    "payableStatus": duplicate["payable_status"],
                    "netAmount": float(duplicate["net_amount"] or 0),
                })
                return result

            payable_status = "CLOSED" if net_amount <= 0.01 else "UNPAID"
            cur.execute(
                """insert into vendor_invoices(
                     vendor_code,site,production_cycle_id,purchase_order_id,goods_receipt_id,
                     invoice_number,invoice_date,gross_amount,reject_deduction,net_amount,
                     evidence_uri,payable_status,due_date,source_key
                   ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                (
                    ctx["vendor_code"], ctx["site"], ctx["production_cycle_id"], ctx["purchase_order_id"],
                    ctx["goods_receipt_id"], payload.invoice_number, payload.invoice_date, gross_amount,
                    reject_deduction, net_amount, payload.evidence_uri, payable_status, payload.due_date, source_key,
                ),
            )
            invoice_id = cur.fetchone()["id"]
            for line in resolved:
                cur.execute(
                    """insert into vendor_invoice_items(
                         vendor_invoice_id,item_code,item_name,invoiced_qty,unit,vendor_cost_price,line_total,
                         purchase_order_item_id,goods_receipt_item_id,accepted_qty_snapshot,rejected_qty,payable_qty,
                         reject_amount,po_qty_snapshot,invoice_vs_po_variance,invoice_vs_receipt_variance
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        invoice_id, line["item_code"], line["item_name"], line["invoiced_qty"], line["unit"],
                        line["vendor_cost_price"], line["line_total"], line["purchase_order_item_id"],
                        line["goods_receipt_item_id"], line["accepted_qty"], line["rejected_qty"],
                        line["payable_qty"], line["reject_amount"], line["po_qty"],
                        line["invoice_vs_po_variance"], line["invoice_vs_receipt_variance"],
                    ),
                )
            conn.commit()
            result.update({"committed": True, "duplicate": False, "vendorInvoiceId": invoice_id})
            return result


@router.post("/vendor-payables/{invoice_id}/correct")
def correct_vendor_payable(invoice_id: int, payload: VendorPayableCorrectionIn) -> dict[str, Any]:
    """Correct an unpaid vendor payable without rewriting its PO/receipt trail."""
    require_db()
    net_amount = round(max(float(payload.gross_amount) - float(payload.reject_deduction), 0), 2)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id,payable_status from vendor_invoices where id=%s", (invoice_id,))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(404, "tagihan vendor tidak ditemukan")
            if str(existing.get("payable_status") or "UNPAID").upper() in {"PAID", "RECONCILED", "CANCELLED", "CANCELED"}:
                raise HTTPException(409, "tagihan yang sudah dibayar/ditutup tidak dapat dikoreksi")
            status = "CLOSED" if net_amount <= 0.01 else "UNPAID"
            cur.execute("""
                update vendor_invoices
                   set invoice_number=%s,invoice_date=%s,due_date=%s,gross_amount=%s,reject_deduction=%s,
                       net_amount=%s,payable_status=%s,correction_note=%s,updated_at=now()
                 where id=%s
                 returning id as vendor_invoice_id,invoice_number,invoice_date,due_date,gross_amount,
                           reject_deduction,net_amount,payable_status
            """, (payload.invoice_number or None, payload.invoice_date, payload.due_date, payload.gross_amount,
                    payload.reject_deduction, net_amount, status, payload.correction_note.strip(), invoice_id))
            row = dict(cur.fetchone())
            conn.commit()
    return {"committed": True, "correctionNote": payload.correction_note, "item": row}


@router.delete("/vendor-payables/{invoice_id}")
def delete_unpaid_vendor_payable(invoice_id: int) -> dict[str, Any]:
    """Remove a rejected/unpaid payable only; the PO and goods receipt stay intact."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id,net_amount,payable_status from vendor_invoices where id=%s", (invoice_id,))
            invoice = cur.fetchone()
            if not invoice:
                raise HTTPException(404, "tagihan vendor tidak ditemukan")
            cur.execute("select count(*) as count from vendor_payments where vendor_invoice_id=%s", (invoice_id,))
            if int(cur.fetchone()["count"] or 0) > 0:
                raise HTTPException(409, "tagihan tidak dapat dihapus karena sudah memiliki bukti pembayaran")
            if float(invoice.get("net_amount") or 0) > 0.01:
                raise HTTPException(409, "hanya tagihan netto Rp0/reject yang dapat dihapus dari layar ini")
            cur.execute("delete from vendor_invoice_items where vendor_invoice_id=%s", (invoice_id,))
            cur.execute("delete from vendor_invoices where id=%s", (invoice_id,))
            conn.commit()
    return {"deleted": True, "vendorInvoiceId": invoice_id, "poReceiptPreserved": True}


@router.get("/vendor-payables")
def list_vendor_payables(
    site: str = "",
    vendor: str = "",
    status: str = "",
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    require_db()
    sql = """select vi.id as vendor_invoice_id,vi.vendor_code,vi.site,vi.purchase_order_id,vi.goods_receipt_id,
                    vi.invoice_number,vi.invoice_date,vi.gross_amount,vi.reject_deduction,vi.net_amount,
                    vi.payable_status,vi.due_date,vi.created_at,po.po_code,pc.distribution_date
             from vendor_invoices vi
             left join purchase_orders po on po.id=vi.purchase_order_id
             left join production_cycles pc on pc.id=vi.production_cycle_id
             where true"""
    params: list[Any] = []
    if site:
        sql += " and upper(vi.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(vi.vendor_code)=upper(%s)"
        params.append(vendor)
    if status:
        sql += " and upper(vi.payable_status)=upper(%s)"
        params.append(status)
    sql += " order by vi.created_at desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return {"items": cur.fetchall()}
