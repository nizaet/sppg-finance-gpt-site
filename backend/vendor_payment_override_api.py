from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.gpt_bridge_api import _sync_row, _update_sync_status
from backend.vendor_workflow_api import VENDOR_EXPENSE_CATEGORIES, VENDOR_LABELS

router = APIRouter(tags=["vendor-payment-override"])


class VendorPaymentEvidenceIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    vendor_code: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0)
    paid_at: datetime | None = None
    payment_source: str | None = None
    reference_number: str | None = None
    evidence_uri: str | None = None
    source_external_id: str | None = None
    purchase_order_id: int | None = None
    goods_receipt_id: int | None = None
    vendor_invoice_id: int | None = None
    note: str = ""
    actor: str = "chatgpt"
    commit: bool = False


class VendorPaymentReconcileIn(BaseModel):
    vendor_invoice_id: int = Field(gt=0)
    note: str = ""
    actor: str = "chatgpt"
    commit: bool = False


def _require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _payment_key(payload: VendorPaymentEvidenceIn) -> str:
    canonical = {
        "site": payload.site,
        "vendor": payload.vendor_code.upper().strip(),
        "amount": round(float(payload.amount), 2),
        "paid_at": payload.paid_at.isoformat() if payload.paid_at else None,
        "payment_source": payload.payment_source,
        "reference_number": payload.reference_number,
        "evidence_uri": payload.evidence_uri,
        "source_external_id": payload.source_external_id,
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return "vendor-payment-evidence:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _candidate_invoices(cur: Any, payload: VendorPaymentEvidenceIn) -> list[dict[str, Any]]:
    sql = """
        select vi.id,vi.vendor_code,vi.site,vi.net_amount,vi.payable_status,vi.invoice_number,
               vi.purchase_order_id,vi.goods_receipt_id,po.po_code,vi.created_at,
               coalesce((select sum(vp.amount) from vendor_payments vp
                         where vp.vendor_invoice_id=vi.id and vp.payment_status in ('PAID','RECONCILED')),0) as paid_total
        from vendor_invoices vi
        left join purchase_orders po on po.id=vi.purchase_order_id
        where upper(vi.site)=upper(%s) and upper(vi.vendor_code)=upper(%s)
    """
    params: list[Any] = [payload.site, payload.vendor_code.upper().strip()]
    if payload.vendor_invoice_id is not None:
        sql += " and vi.id=%s"
        params.append(payload.vendor_invoice_id)
    if payload.purchase_order_id is not None:
        sql += " and vi.purchase_order_id=%s"
        params.append(payload.purchase_order_id)
    if payload.goods_receipt_id is not None:
        sql += " and vi.goods_receipt_id=%s"
        params.append(payload.goods_receipt_id)
    sql += " order by vi.created_at desc,vi.id desc limit 20"
    cur.execute(sql, params)
    rows = cur.fetchall()
    for row in rows:
        row["remaining_amount"] = round(max(float(row.get("net_amount") or 0) - float(row.get("paid_total") or 0), 0.0), 2)
    return rows


def _safe_invoice(rows: list[dict[str, Any]], amount: float, explicit_id: int | None) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if explicit_id is not None:
        if not rows:
            warnings.append("vendor_invoice_id tidak ditemukan untuk site/vendor/PO/GR yang diberikan")
            return None, warnings
        row = rows[0]
        if amount > float(row.get("remaining_amount") or 0) + 0.01:
            warnings.append("nominal pembayaran melebihi sisa invoice; transfer tetap dapat dicatat sebagai PAID_UNRECONCILED")
            return None, warnings
        return row, warnings

    eligible = [row for row in rows if float(row.get("remaining_amount") or 0) > 0.01 and amount <= float(row.get("remaining_amount") or 0) + 0.01]
    if len(eligible) == 1:
        return eligible[0], warnings
    if len(eligible) > 1:
        warnings.append("lebih dari satu payable cocok; transfer akan disimpan PAID_UNRECONCILED")
    else:
        warnings.append("belum ada payable yang aman untuk dipasangkan; transfer akan disimpan PAID_UNRECONCILED")
    return None, warnings


def _safe_candidate_refs(cur: Any, payload: VendorPaymentEvidenceIn, warnings: list[str]) -> tuple[int | None, int | None]:
    po_id = None
    gr_id = None
    vendor = payload.vendor_code.upper().strip()
    if payload.purchase_order_id is not None:
        cur.execute("select id from purchase_orders where id=%s and upper(site)=upper(%s) and upper(vendor_code)=upper(%s)",
                    (payload.purchase_order_id, payload.site, vendor))
        row = cur.fetchone()
        if row:
            po_id = int(row["id"])
        else:
            warnings.append("candidate purchase_order_id diabaikan karena tidak cocok dengan site/vendor")
    if payload.goods_receipt_id is not None:
        cur.execute("""
            select gr.id from goods_receipts gr join purchase_orders po on po.id=gr.purchase_order_id
            where gr.id=%s and upper(po.site)=upper(%s) and upper(po.vendor_code)=upper(%s)
        """, (payload.goods_receipt_id, payload.site, vendor))
        row = cur.fetchone()
        if row:
            gr_id = int(row["id"])
        else:
            warnings.append("candidate goods_receipt_id diabaikan karena tidak cocok dengan site/vendor")
    return po_id, gr_id


def _update_invoice_status(cur: Any, invoice_id: int) -> str:
    cur.execute("select net_amount from vendor_invoices where id=%s", (invoice_id,))
    invoice = cur.fetchone()
    if not invoice:
        raise HTTPException(404, "vendor invoice not found")
    cur.execute("""
        select coalesce(sum(amount),0) as paid from vendor_payments
        where vendor_invoice_id=%s and payment_status in ('PAID','RECONCILED')
    """, (invoice_id,))
    paid = float(cur.fetchone()["paid"] or 0)
    net = float(invoice.get("net_amount") or 0)
    status = "PAID" if paid >= net - 0.01 else ("PARTIAL" if paid > 0.01 else "UNPAID")
    cur.execute("update vendor_invoices set payable_status=%s,updated_at=now() where id=%s", (status, invoice_id))
    return status


def _invoice_payment_items(cur: Any, invoice: dict[str, Any] | None, payment_amount: float) -> list[dict[str, Any]]:
    """Allocate a paid vendor invoice to its persisted invoice items.

    Full payments keep the exact invoice qty/price. Partial payments are
    proportional, preserving the original unit price instead of inventing one.
    """
    if not invoice:
        return []
    cur.execute("""
        select vii.id,vii.item_code,vii.item_name,
               coalesce(
                 nullif(to_jsonb(vii)->>'payable_qty','')::numeric,
                 vii.invoiced_qty,
                 0
               ) as payable_qty,
               vii.unit,coalesce(vii.vendor_cost_price,0) as vendor_cost_price,
               coalesce(vii.line_total,0) as line_total
        from vendor_invoice_items vii
        where vii.vendor_invoice_id=%s
        order by vii.id
    """, (invoice["id"],))
    rows = [dict(row) for row in cur.fetchall()]
    total = round(sum(float(row.get("line_total") or 0) for row in rows), 2)
    if not rows or total <= 0:
        return []
    factor = min(1.0, round(float(payment_amount) / total, 10))
    allocated: list[dict[str, Any]] = []
    remaining = round(float(payment_amount), 2)
    for index, row in enumerate(rows):
        amount = round(float(row["line_total"]) * factor, 2) if index < len(rows) - 1 else remaining
        amount = max(0.0, amount)
        remaining = round(remaining - amount, 2)
        allocated.append({**row, "allocated_amount": amount,
                          "allocated_qty": round(float(row.get("payable_qty") or 0) * factor, 4)})
    return [row for row in allocated if row["allocated_amount"] > 0]


def _finance_rows(cur: Any, payment_id: int, payload: VendorPaymentEvidenceIn, paid_at: datetime,
                  invoice: dict[str, Any] | None) -> tuple[list[dict[str, Any]], int]:
    """Persist one finance row per vendor invoice item, for every vendor."""
    site, vendor = payload.site, payload.vendor_code.upper().strip()
    amount = round(float(payload.amount), 2)
    label = VENDOR_LABELS.get(vendor, vendor)
    category = VENDOR_EXPENSE_CATEGORIES.get(vendor, "Bahan Baku")
    status = "RECONCILED" if invoice else "PAID_UNRECONCILED"
    item_rows = _invoice_payment_items(cur, invoice, amount)
    if not item_rows:
        # Payment without a resolved invoice remains one clearly marked row;
        # it cannot be itemized safely until its invoice detail exists.
        item_rows = [{"id": None, "item_code": None, "item_name": f"Pembayaran {label}",
                      "allocated_qty": 1, "unit": "invoice", "vendor_cost_price": amount,
                      "allocated_amount": amount}]

    persisted: list[dict[str, Any]] = []
    inserted_count = 0
    for index, item in enumerate(item_rows):
        item_id = item.get("id")
        tx_id = f"vendorpay_{site.lower()}_{payment_id}" if index == 0 else f"vendorpay_{site.lower()}_{payment_id}_item_{item_id}"
        idem_raw = json.dumps({"site": site, "payment_id": payment_id, "item_id": item_id or index,
                               "amount": item["allocated_amount"], "paid_date": paid_at.date().isoformat()}, sort_keys=True)
        idem = "fin:auto-vendor-payment-item:" + hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()
        item_name = str(item.get("item_name") or "Item invoice")
        description = " - ".join(filter(None, [f"Pembayaran {label}", str(invoice.get("invoice_number")) if invoice and invoice.get("invoice_number") else "", item_name]))
        note = " | ".join(filter(None, [
            "Otomatis per item dari bukti pembayaran vendor", f"vendor={vendor}", f"vendor_payment_id={payment_id}",
            f"vendor_invoice_item_id={item_id}" if item_id else "", f"reconciliation={status}",
            f"payment_source={payload.payment_source}" if payload.payment_source else "",
            f"reference={payload.reference_number}" if payload.reference_number else "", payload.note.strip(),
        ]))
        raw_text = json.dumps({"vendorPaymentId": payment_id, "vendorInvoiceId": invoice["id"] if invoice else None,
                               "vendorInvoiceItemId": item_id, "vendorCode": vendor, "site": site,
                               "amount": float(item["allocated_amount"] or 0), "qty": float(item["allocated_qty"] or 0),
                               "unit": item.get("unit"), "unitPrice": float(item.get("vendor_cost_price") or 0),
                               "paidAt": paid_at.isoformat(), "reconciliationStatus": status}, ensure_ascii=False)
        values = (idem, site, paid_at.date(), description, category, item["allocated_amount"], item["allocated_qty"],
                  item.get("unit") or "item", item.get("vendor_cost_price") or 0, label,
                  item["allocated_amount"], paid_at.date(), f"vendor-payment:{payment_id}:item:{item_id or index}",
                  raw_text, f"Pembayaran item vendor {vendor}; reconciliation={status}.", note, payload.evidence_uri, tx_id)
        cur.execute("select transaction_id from finance_transactions where transaction_id=%s", (tx_id,))
        exists = cur.fetchone()
        if exists:
            cur.execute("""
                update finance_transactions set idempotency_key=%s,site=%s,transaction_date=%s,description=%s,
                    transaction_type='expense',category=%s,amount=%s,qty=%s,unit=%s,unit_price=%s,order_by=%s,
                    is_debt=false,payment_status='paid',paid_amount=%s,paid_date=%s,source='vendor_payment_item_auto',
                    source_ref=%s,raw_text=%s,classification_confidence=0.99,classification_reason=%s,note=%s,
                    evidence_uri=%s,updated_at=now() where transaction_id=%s
            """, values)
        else:
            cur.execute("""
                insert into finance_transactions(
                  transaction_id,idempotency_key,site,transaction_date,description,transaction_type,category,amount,qty,unit,
                  unit_price,order_by,is_debt,payment_status,paid_amount,paid_date,source,source_ref,raw_text,
                  classification_confidence,classification_reason,note,evidence_uri
                ) values (%s,%s,%s,%s,%s,'expense',%s,%s,%s,%s,%s,%s,false,'paid',%s,%s,
                          'vendor_payment_item_auto',%s,%s,0.99,%s,%s,%s)
            """, (tx_id, *values[:-1]))
            inserted_count += 1
        cur.execute("select * from finance_transactions where transaction_id=%s", (tx_id,))
        persisted.append(dict(cur.fetchone()))
    cur.execute("update vendor_payments set finance_transaction_id=%s,updated_at=now() where id=%s",
                (persisted[0]["transaction_id"], payment_id))
    return persisted, inserted_count

@router.post("/vendor-payments/record-evidence")
def record_vendor_payment_evidence(payload: VendorPaymentEvidenceIn) -> dict[str, Any]:
    _require_db()
    vendor = payload.vendor_code.upper().strip()
    paid_at = payload.paid_at or datetime.now(timezone.utc)
    amount = round(float(payload.amount), 2)
    key = _payment_key(payload)

    with connection() as conn:
        with conn.cursor() as cur:
            rows = _candidate_invoices(cur, payload)
            invoice, warnings = _safe_invoice(rows, amount, payload.vendor_invoice_id)
            po_id, gr_id = _safe_candidate_refs(cur, payload, warnings)
            candidate_invoice_id = int(rows[0]["id"]) if payload.vendor_invoice_id is not None and rows and not invoice else None
            result: dict[str, Any] = {
                "committed": False, "canCommit": True, "site": payload.site, "vendorCode": vendor, "amount": amount,
                "paidAt": paid_at, "paymentStatus": "PAID", "reconciliationStatus": "RECONCILED" if invoice else "PAID_UNRECONCILED",
                "vendorInvoiceId": invoice["id"] if invoice else None, "candidatePurchaseOrderId": po_id,
                "candidateGoodsReceiptId": gr_id, "candidateVendorInvoiceId": candidate_invoice_id,
                "candidateInvoices": [{"vendorInvoiceId": row["id"], "invoiceNumber": row.get("invoice_number"),
                                       "purchaseOrderId": row.get("purchase_order_id"), "goodsReceiptId": row.get("goods_receipt_id"),
                                       "netAmount": float(row.get("net_amount") or 0), "remainingAmount": float(row.get("remaining_amount") or 0)}
                                      for row in rows[:10]],
                "warnings": warnings, "financeTransactionCreated": False,
            }
            if not payload.commit:
                return result

            cur.execute("select * from vendor_payments where source_key=%s", (key,))
            payment = cur.fetchone()
            duplicate = bool(payment)
            if payment:
                payment_id = int(payment["id"])
                if payment.get("vendor_invoice_id"):
                    cur.execute("""
                        select vi.*,po.po_code from vendor_invoices vi
                        left join purchase_orders po on po.id=vi.purchase_order_id where vi.id=%s
                    """, (payment["vendor_invoice_id"],))
                    invoice = cur.fetchone()
            else:
                status = "RECONCILED" if invoice else "PAID_UNRECONCILED"
                cur.execute("""
                    insert into vendor_payments(
                      vendor_invoice_id,vendor_code,site,amount,payment_status,payment_source,paid_at,evidence_uri,
                      reference_number,source_key,candidate_purchase_order_id,candidate_goods_receipt_id,candidate_vendor_invoice_id,
                      reconciliation_note,source_external_id,actor,reconciled_at
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id
                """, (invoice["id"] if invoice else None, vendor, payload.site, amount, status, payload.payment_source, paid_at,
                      payload.evidence_uri, payload.reference_number, key, po_id, gr_id, candidate_invoice_id, payload.note or None,
                      payload.source_external_id, payload.actor, datetime.now(timezone.utc) if invoice else None))
                payment_id = int(cur.fetchone()["id"])

            payable_status = _update_invoice_status(cur, int(invoice["id"])) if invoice else None
            finance_rows, finance_inserted = _finance_rows(cur, payment_id, payload, paid_at, invoice)
            conn.commit()

    sync_results = []
    for finance_row in finance_rows:
        sync_status, firestore_path, firestore_doc_id, sync_error = _sync_row(finance_row)
        _update_sync_status(finance_row["transaction_id"], sync_status, firestore_doc_id, sync_error, payload.evidence_uri)
        sync_results.append({"transactionId": finance_row["transaction_id"], "status": sync_status,
                             "document": firestore_path, "error": sync_error})
    result.update({"committed": True, "duplicate": duplicate, "vendorPaymentId": payment_id,
                   "vendorInvoiceId": invoice["id"] if invoice else None, "paymentStatus": "PAID",
                   "reconciliationStatus": "RECONCILED" if invoice else "PAID_UNRECONCILED", "payableStatusAfter": payable_status,
                   "financeTransactionCreated": True, "financeTransactionInserted": finance_inserted,
                   "financeTransactionId": finance_rows[0]["transaction_id"], "financeTransactionCount": len(finance_rows),
                   "financeTransactions": sync_results,
                   "firestoreSyncStatus": "SYNCED" if all(x["status"] == "SYNCED" for x in sync_results) else "PARTIAL"})
    return result


@router.post("/vendor-payments/itemize-finance")
def itemize_vendor_payment_finance(site: Literal["MAJA", "CEMPLANG"] | None = None) -> dict[str, Any]:
    """Convert old aggregate vendor-payment rows into their invoice-item rows.

    Safe to run repeatedly: the first legacy row is rewritten in place and the
    remaining invoice items use stable ids, so no double expense is created.
    """
    _require_db()
    synced_rows: list[dict[str, Any]] = []
    inserted = 0
    processed = 0
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select vp.id as payment_id,vp.site,vp.vendor_code,vp.amount,vp.paid_at,vp.payment_source,
                       vp.reference_number,vp.evidence_uri,vp.source_external_id,vp.reconciliation_note,
                       vi.id,vi.invoice_number,vi.net_amount,vi.purchase_order_id,vi.goods_receipt_id,po.po_code
                from vendor_payments vp
                join vendor_invoices vi on vi.id=vp.vendor_invoice_id
                left join purchase_orders po on po.id=vi.purchase_order_id
                where vp.payment_status in ('PAID','RECONCILED')
            """
            params: list[Any] = []
            if site:
                sql += " and upper(vp.site)=upper(%s)"
                params.append(site)
            sql += " order by vp.id"
            cur.execute(sql, params)
            payments = [dict(row) for row in cur.fetchall()]
            for payment in payments:
                payload = VendorPaymentEvidenceIn(
                    site=str(payment["site"]).upper(), vendor_code=str(payment["vendor_code"]),
                    amount=float(payment["amount"]), paid_at=payment.get("paid_at"),
                    payment_source=payment.get("payment_source"), reference_number=payment.get("reference_number"),
                    evidence_uri=payment.get("evidence_uri"), source_external_id=payment.get("source_external_id"),
                    purchase_order_id=payment.get("purchase_order_id"), goods_receipt_id=payment.get("goods_receipt_id"),
                    vendor_invoice_id=int(payment["id"]), note=str(payment.get("reconciliation_note") or ""),
                    actor="itemize-backfill", commit=True,
                )
                invoice = {
                    "id": int(payment["id"]), "invoice_number": payment.get("invoice_number"),
                    "po_code": payment.get("po_code"), "net_amount": payment.get("net_amount"),
                }
                rows, created = _finance_rows(cur, int(payment["payment_id"]), payload,
                                              payment.get("paid_at") or datetime.now(timezone.utc), invoice)
                synced_rows.extend(rows); inserted += created; processed += 1
            conn.commit()
    outcomes = []
    for row in synced_rows:
        status, path, doc_id, error = _sync_row(row)
        _update_sync_status(row["transaction_id"], status, doc_id, error, row.get("evidence_uri"))
        outcomes.append({"transactionId": row["transaction_id"], "status": status, "error": error})
    return {"site": site, "paymentsProcessed": processed, "financeRows": len(synced_rows),
            "newRows": inserted, "synced": sum(1 for x in outcomes if x["status"] == "SYNCED"),
            "failed": sum(1 for x in outcomes if x["status"] != "SYNCED"), "results": outcomes}


@router.post("/vendor-payments/{payment_id}/reconcile")
def reconcile_vendor_payment(payment_id: int, payload: VendorPaymentReconcileIn) -> dict[str, Any]:
    _require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from vendor_payments where id=%s", (payment_id,))
            payment = cur.fetchone()
            if not payment:
                raise HTTPException(404, "vendor payment not found")
            cur.execute("""
                select vi.id,vi.vendor_code,vi.site,vi.net_amount,vi.invoice_number,vi.purchase_order_id,vi.goods_receipt_id,po.po_code
                from vendor_invoices vi left join purchase_orders po on po.id=vi.purchase_order_id where vi.id=%s
            """, (payload.vendor_invoice_id,))
            invoice = cur.fetchone()
            if not invoice:
                raise HTTPException(404, "vendor invoice not found")
            if str(invoice["site"]).upper() != str(payment.get("site") or "").upper():
                raise HTTPException(409, "payment and invoice site do not match")
            if str(invoice["vendor_code"]).upper() != str(payment.get("vendor_code") or "").upper():
                raise HTTPException(409, "payment and invoice vendor do not match")
            if payment.get("vendor_invoice_id") not in (None, invoice["id"]):
                raise HTTPException(409, "payment is already reconciled to a different invoice")

            cur.execute("""
                select coalesce(sum(amount),0) as paid from vendor_payments
                where vendor_invoice_id=%s and id<>%s and payment_status in ('PAID','RECONCILED')
            """, (invoice["id"], payment_id))
            remaining = max(float(invoice.get("net_amount") or 0) - float(cur.fetchone()["paid"] or 0), 0.0)
            amount = float(payment.get("amount") or 0)
            can_commit = amount <= remaining + 0.01 or payment.get("vendor_invoice_id") == invoice["id"]
            result = {"committed": False, "canCommit": can_commit, "vendorPaymentId": payment_id,
                      "vendorInvoiceId": invoice["id"], "vendorCode": invoice["vendor_code"], "site": invoice["site"],
                      "paymentAmount": amount, "invoiceRemainingBefore": round(remaining, 2),
                      "reconciliationStatus": "RECONCILED" if can_commit else "CONFLICT",
                      "reason": None if can_commit else "payment exceeds invoice remaining; split reconciliation is required"}
            if not payload.commit:
                return result
            if not can_commit:
                raise HTTPException(409, detail=result)
            if payment.get("vendor_invoice_id") == invoice["id"] and str(payment.get("payment_status") or "").upper() == "RECONCILED":
                result.update({"committed": True, "duplicate": True, "payableStatusAfter": _update_invoice_status(cur, int(invoice["id"]))})
                conn.commit()
                return result

            cur.execute("""
                update vendor_payments set vendor_invoice_id=%s,payment_status='RECONCILED',candidate_vendor_invoice_id=null,
                    reconciliation_note=concat_ws(' | ',nullif(reconciliation_note,''),nullif(%s,'')),actor=%s,
                    reconciled_at=now(),updated_at=now() where id=%s
            """, (invoice["id"], payload.note, payload.actor, payment_id))
            status = _update_invoice_status(cur, int(invoice["id"]))
            cur.execute("""
                insert into finance_bridge_audit_log(transaction_id,action,actor,details)
                select finance_transaction_id,'RECONCILE_VENDOR_PAYMENT',%s,%s::jsonb
                from vendor_payments where id=%s and finance_transaction_id is not null
            """, (payload.actor, json.dumps({"vendor_payment_id": payment_id, "vendor_invoice_id": invoice["id"]}), payment_id))
            conn.commit()
            result.update({"committed": True, "duplicate": False, "reconciliationStatus": "RECONCILED", "payableStatusAfter": status})
            return result


@router.get("/vendor-payments/unreconciled")
def list_unreconciled_vendor_payments(site: str = "", vendor: str = "", limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    _require_db()
    sql = """
        select id,vendor_code,site,amount,payment_status,payment_source,paid_at,evidence_uri,reference_number,
               candidate_purchase_order_id,candidate_goods_receipt_id,candidate_vendor_invoice_id,reconciliation_note,
               source_external_id,actor,finance_transaction_id,created_at
        from vendor_payments where payment_status='PAID_UNRECONCILED'
    """
    params: list[Any] = []
    if site:
        sql += " and upper(site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by paid_at desc nulls last,id desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return {"items": cur.fetchall()}
