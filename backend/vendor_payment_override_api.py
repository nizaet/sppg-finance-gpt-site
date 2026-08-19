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


def _finance_row(cur: Any, payment_id: int, payload: VendorPaymentEvidenceIn, paid_at: datetime,
                 invoice: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    site = payload.site
    vendor = payload.vendor_code.upper().strip()
    amount = round(float(payload.amount), 2)
    label = VENDOR_LABELS.get(vendor, vendor)
    category = VENDOR_EXPENSE_CATEGORIES.get(vendor, "Bahan Baku")
    source_ref = f"vendor-payment:{payment_id}"
    idem_raw = json.dumps({"site": site, "payment_id": payment_id, "amount": amount, "paid_date": paid_at.date().isoformat()}, sort_keys=True)
    idem = "fin:auto-vendor-payment:" + hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()
    tx_id = f"vendorpay_{site.lower()}_{payment_id}"
    status = "RECONCILED" if invoice else "PAID_UNRECONCILED"
    parts = [f"Pembayaran {label}"]
    if invoice and invoice.get("invoice_number"):
        parts.append(str(invoice["invoice_number"]))
    if invoice and invoice.get("po_code"):
        parts.append(str(invoice["po_code"]))
    description = " - ".join(parts)
    note = " | ".join(filter(None, [
        "Otomatis dari bukti pembayaran vendor", f"vendor={vendor}", f"vendor_payment_id={payment_id}",
        f"reconciliation={status}", f"payment_source={payload.payment_source}" if payload.payment_source else "",
        f"reference={payload.reference_number}" if payload.reference_number else "", payload.note.strip(),
    ]))
    raw_text = json.dumps({"vendorPaymentId": payment_id, "vendorInvoiceId": invoice["id"] if invoice else None,
                           "vendorCode": vendor, "site": site, "amount": amount, "paidAt": paid_at.isoformat(),
                           "reconciliationStatus": status, "sourceExternalId": payload.source_external_id}, ensure_ascii=False)
    cur.execute("""
        insert into finance_transactions(
          transaction_id,idempotency_key,site,transaction_date,description,transaction_type,category,amount,qty,unit,
          unit_price,order_by,is_debt,payment_status,paid_amount,paid_date,source,source_ref,raw_text,
          classification_confidence,classification_reason,note,evidence_uri
        ) values (%s,%s,%s,%s,%s,'expense',%s,%s,null,null,null,%s,false,'paid',%s,%s,
                  'vendor_payment_auto',%s,%s,0.99,%s,%s,%s)
        on conflict (idempotency_key) do nothing returning transaction_id
    """, (tx_id, idem, site, paid_at.date(), description, category, amount, label, amount, paid_at.date(), source_ref,
          raw_text, f"Pembayaran vendor {vendor} sudah terjadi; reconciliation={status}.", note, payload.evidence_uri))
    inserted = cur.fetchone()
    cur.execute("select * from finance_transactions where idempotency_key=%s", (idem,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(500, "finance transaction was not persisted for vendor payment evidence")
    cur.execute("update vendor_payments set finance_transaction_id=%s,updated_at=now() where id=%s", (row["transaction_id"], payment_id))
    cur.execute("""
        insert into finance_bridge_audit_log(transaction_id,action,actor,details)
        values (%s,%s,%s,%s::jsonb)
    """, (row["transaction_id"], "AUTO_VENDOR_PAYMENT_EVIDENCE_CREATE" if inserted else "AUTO_VENDOR_PAYMENT_EVIDENCE_REPLAY",
          payload.actor, json.dumps({"vendor_payment_id": payment_id, "vendor_invoice_id": invoice["id"] if invoice else None,
                                     "vendor_code": vendor, "amount": amount, "reconciliation_status": status}, ensure_ascii=False)))
    return row, bool(inserted)


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
            finance_row, finance_inserted = _finance_row(cur, payment_id, payload, paid_at, invoice)
            conn.commit()

    sync_status, firestore_path, firestore_doc_id, sync_error = _sync_row(finance_row)
    _update_sync_status(finance_row["transaction_id"], sync_status, firestore_doc_id, sync_error, payload.evidence_uri)
    result.update({"committed": True, "duplicate": duplicate, "vendorPaymentId": payment_id,
                   "vendorInvoiceId": invoice["id"] if invoice else None, "paymentStatus": "PAID",
                   "reconciliationStatus": "RECONCILED" if invoice else "PAID_UNRECONCILED", "payableStatusAfter": payable_status,
                   "financeTransactionCreated": True, "financeTransactionInserted": finance_inserted,
                   "financeTransactionId": finance_row["transaction_id"], "firestoreSyncStatus": sync_status,
                   "firestoreDocument": firestore_path, "syncError": sync_error})
    return result


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
