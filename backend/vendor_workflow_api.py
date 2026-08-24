from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.gpt_bridge_api import _sync_row, _update_sync_status
from backend.vendor_invoice_parser import parse_vendor_invoice_text, payment_draft

router = APIRouter(prefix="/v1", tags=["vendor-workflow"])
ROOT = Path(__file__).resolve().parents[1]


@router.get("/schema/chatgpt-operations-v0161.yaml", response_class=PlainTextResponse, include_in_schema=False)
def chatgpt_operations_schema() -> str:
    path = ROOT / "api" / "openapi_chatgpt_operations_v0161.yaml"
    if not path.exists():
        raise HTTPException(404, "operations schema not found")
    return path.read_text(encoding="utf-8")


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


VENDOR_LABELS = {
    "HOLIL": "Haji Holil",
    "WIKIAN": "Wikian",
    "HAJI_BADRI": "Haji Badri",
    "RUMAH_DUTA_PANGAN": "Rumah Duta Pangan",
    "HERU": "Heru",
    "DEDE": "Dede",
    "KOPERASI": "Koperasi / Mungki",
}

VENDOR_EXPENSE_CATEGORIES = {
    "HOLIL": "Sayur/Buah",
    "WIKIAN": "Lauk",
    "RUMAH_DUTA_PANGAN": "Lauk",
    "HAJI_BADRI": "Lauk",
    "DEDE": "Sembako/Bumbu",
    "HERU": "Utilitas",
    "KOPERASI": "Sembako/Bumbu",
}


class VendorInvoiceTextIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    vendor_code: str = Field(min_length=1)
    invoice_date_label: str = Field(min_length=1)
    text: str = Field(min_length=1)


@router.post("/vendor-invoices/parse-whatsapp")
def parse_vendor_invoice(payload: VendorInvoiceTextIn) -> dict[str, Any]:
    parsed = parse_vendor_invoice_text(payload.text, payload.vendor_code.upper(), payload.site)
    label = VENDOR_LABELS.get(payload.vendor_code.upper(), payload.vendor_code)
    parsed["paymentDraft"] = payment_draft(parsed, label, payload.site.title(), payload.invoice_date_label)
    parsed["financeTransactionCreated"] = False
    return parsed


class VendorPaymentConfirmIn(BaseModel):
    vendor_invoice_id: int
    amount: float = Field(gt=0)
    paid_at: datetime | None = None
    payment_source: str | None = None
    reference_number: str | None = None
    evidence_uri: str | None = None
    source_external_id: str | None = None
    commit: bool = False


def payment_key(payload: VendorPaymentConfirmIn) -> str:
    canonical = {
        "vendor_invoice_id": payload.vendor_invoice_id,
        "amount": round(float(payload.amount), 2),
        "paid_at": payload.paid_at.isoformat() if payload.paid_at else None,
        "reference_number": payload.reference_number,
        "source_external_id": payload.source_external_id,
        "evidence_uri": payload.evidence_uri,
    }
    return "vendor-payment:" + hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _paid_date(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _finance_transaction_values(invoice: dict[str, Any], *, payment_id: int, amount: float, paid_at: datetime, payload: VendorPaymentConfirmIn) -> dict[str, Any]:
    site = str(invoice["site"]).upper()
    vendor = str(invoice["vendor_code"]).upper()
    label = VENDOR_LABELS.get(vendor, vendor)
    category = VENDOR_EXPENSE_CATEGORIES.get(vendor, "Bahan Baku")
    paid_date = paid_at.date()
    source_ref = f"vendor-payment:{payment_id}"
    description_parts = [
        f"Pembayaran {label}",
        f"Invoice Vendor #{invoice['id']}",
    ]
    if invoice.get("invoice_number"):
        description_parts.append(str(invoice["invoice_number"]))
    if invoice.get("po_code"):
        description_parts.append(str(invoice["po_code"]))
    description = " - ".join(description_parts)
    idem_raw = json.dumps({
        "site": site,
        "source_ref": source_ref,
        "vendor_invoice_id": invoice["id"],
        "vendor_payment_id": payment_id,
        "amount": round(amount, 2),
        "paid_date": paid_date.isoformat(),
    }, sort_keys=True, ensure_ascii=False)
    idem = "fin:auto-vendor-payment:" + hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()
    tx_id = f"vendorpay_{site.lower()}_{payment_id}"
    note = " | ".join(filter(None, [
        "Otomatis dari pembayaran vendor",
        f"vendor={vendor}",
        f"vendor_invoice_id={invoice['id']}",
        f"vendor_payment_id={payment_id}",
        f"payment_source={payload.payment_source}" if payload.payment_source else "",
        f"reference={payload.reference_number}" if payload.reference_number else "",
    ]))
    raw_text = json.dumps({
        "vendorInvoiceId": invoice["id"],
        "vendorPaymentId": payment_id,
        "vendorCode": vendor,
        "amount": amount,
        "paidAt": paid_at.isoformat(),
        "referenceNumber": payload.reference_number,
        "paymentSource": payload.payment_source,
    }, ensure_ascii=False, default=str)
    return {
        "transaction_id": tx_id,
        "idempotency_key": idem,
        "site": site,
        "transaction_date": paid_date,
        "description": description,
        "transaction_type": "expense",
        "category": category,
        "amount": amount,
        "qty": None,
        "unit": None,
        "unit_price": None,
        "order_by": label,
        "is_debt": False,
        "payment_status": "paid",
        "paid_amount": amount,
        "paid_date": paid_date,
        "source": "vendor_payment_auto",
        "source_ref": source_ref,
        "raw_text": raw_text,
        "classification_confidence": 0.98,
        "classification_reason": f"Auto-post dari pembayaran vendor {vendor}; kategori berdasarkan mapping vendor.",
        "note": note,
        "evidence_uri": payload.evidence_uri,
    }


def _create_finance_transaction_for_payment(cur: Any, invoice: dict[str, Any], *, payment_id: int, amount: float, paid_at: datetime, payload: VendorPaymentConfirmIn) -> tuple[dict[str, Any], bool]:
    tx = _finance_transaction_values(invoice, payment_id=payment_id, amount=amount, paid_at=paid_at, payload=payload)
    cur.execute(
        """insert into finance_transactions(
             transaction_id,idempotency_key,site,transaction_date,description,transaction_type,
             category,amount,qty,unit,unit_price,order_by,is_debt,payment_status,paid_amount,
             paid_date,source,source_ref,raw_text,classification_confidence,
             classification_reason,note,evidence_uri
           ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                     %s,%s,%s,%s,%s,%s,%s)
           on conflict (idempotency_key) do nothing
           returning transaction_id""",
        (
            tx["transaction_id"], tx["idempotency_key"], tx["site"], tx["transaction_date"],
            tx["description"], tx["transaction_type"], tx["category"], tx["amount"], tx["qty"],
            tx["unit"], tx["unit_price"], tx["order_by"], tx["is_debt"], tx["payment_status"],
            tx["paid_amount"], tx["paid_date"], tx["source"], tx["source_ref"], tx["raw_text"],
            tx["classification_confidence"], tx["classification_reason"], tx["note"], tx["evidence_uri"],
        ),
    )
    inserted = cur.fetchone()
    cur.execute("select * from finance_transactions where idempotency_key=%s", (tx["idempotency_key"],))
    row = cur.fetchone()
    if not row:
        raise HTTPException(500, "finance transaction was not persisted for vendor payment")
    cur.execute(
        """insert into finance_bridge_audit_log(transaction_id,action,actor,details)
           values (%s,%s,%s,%s::jsonb)""",
        (
            row["transaction_id"],
            "AUTO_VENDOR_PAYMENT_CREATE" if inserted else "AUTO_VENDOR_PAYMENT_IDEMPOTENT_REPLAY",
            "vendor_payment_auto",
            json.dumps({
                "vendor_invoice_id": invoice["id"],
                "vendor_payment_id": payment_id,
                "vendor_code": invoice["vendor_code"],
                "amount": amount,
            }, ensure_ascii=False),
        ),
    )
    return row, bool(inserted)


def _existing_finance_for_payment(payment_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from finance_transactions where source_ref=%s", (f"vendor-payment:{payment_id}",))
            return cur.fetchone()


@router.post("/vendor-payments/confirm")
def confirm_vendor_payment(payload: VendorPaymentConfirmIn) -> dict[str, Any]:
    require_db()
    finance_row: dict[str, Any] | None = None
    finance_inserted = False
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select vi.id,vi.vendor_code,vi.site,vi.net_amount,vi.payable_status,vi.invoice_number,
                          vi.purchase_order_id,vi.goods_receipt_id,po.po_code
                   from vendor_invoices vi
                   left join purchase_orders po on po.id=vi.purchase_order_id
                   where vi.id=%s""",
                (payload.vendor_invoice_id,),
            )
            invoice = cur.fetchone()
            if not invoice:
                raise HTTPException(404, "vendor invoice not found")

            cur.execute(
                """select coalesce(sum(amount),0) as paid
                   from vendor_payments
                   where vendor_invoice_id=%s and payment_status in ('PAID','RECONCILED')""",
                (payload.vendor_invoice_id,),
            )
            already_paid = float(cur.fetchone()["paid"] or 0)
            net_amount = float(invoice["net_amount"] or 0)
            remaining_before = max(net_amount - already_paid, 0)
            amount = round(float(payload.amount), 2)
            if amount > remaining_before + 0.01:
                raise HTTPException(409, f"payment exceeds remaining payable {remaining_before:.2f}")

            remaining_after = max(remaining_before - amount, 0)
            new_status = "PAID" if remaining_after <= 0.01 else "PARTIAL"
            result = {
                "committed": False,
                "vendorInvoiceId": invoice["id"],
                "vendorCode": invoice["vendor_code"],
                "site": invoice["site"],
                "invoiceNumber": invoice["invoice_number"],
                "netAmount": net_amount,
                "alreadyPaid": already_paid,
                "paymentAmount": amount,
                "remainingBefore": remaining_before,
                "remainingAfter": remaining_after,
                "payableStatusAfter": new_status,
                "canCommit": remaining_before > 0 and amount > 0,
                "financeTransactionCreated": False,
            }
            if not payload.commit:
                return result

            key = payment_key(payload)
            cur.execute("select id,payment_status from vendor_payments where source_key=%s", (key,))
            existing = cur.fetchone()
            if existing:
                existing_finance = _existing_finance_for_payment(int(existing["id"]))
                result.update({
                    "committed": True,
                    "duplicate": True,
                    "vendorPaymentId": existing["id"],
                    "financeTransactionCreated": bool(existing_finance),
                    "financeTransactionId": existing_finance["transaction_id"] if existing_finance else None,
                    "firestoreSyncStatus": existing_finance.get("firestore_sync_status") if existing_finance else None,
                    "firestoreDocument": existing_finance.get("firestore_doc_id") if existing_finance else None,
                })
                return result

            paid_at = _paid_date(payload.paid_at)
            cur.execute(
                """insert into vendor_payments(
                     vendor_invoice_id,vendor_code,site,amount,payment_status,payment_source,paid_at,
                     evidence_uri,reference_number,source_key
                   ) values (%s,%s,%s,%s,'PAID',%s,%s,%s,%s,%s) returning id""",
                (
                    invoice["id"], invoice["vendor_code"], invoice["site"], amount,
                    payload.payment_source, paid_at, payload.evidence_uri,
                    payload.reference_number, key,
                ),
            )
            payment_id = cur.fetchone()["id"]
            cur.execute(
                "update vendor_invoices set payable_status=%s,updated_at=now() where id=%s",
                (new_status, invoice["id"]),
            )
            finance_row, finance_inserted = _create_finance_transaction_for_payment(
                cur,
                invoice,
                payment_id=payment_id,
                amount=amount,
                paid_at=paid_at,
                payload=payload,
            )
            conn.commit()

    sync_status = None
    firestore_path = None
    firestore_doc_id = None
    sync_error = None
    if finance_row:
        sync_status, firestore_path, firestore_doc_id, sync_error = _sync_row(finance_row)
        _update_sync_status(finance_row["transaction_id"], sync_status, firestore_doc_id, sync_error, payload.evidence_uri)

    result.update({
        "committed": True,
        "duplicate": False,
        "vendorPaymentId": payment_id,
        "financeTransactionCreated": True,
        "financeTransactionInserted": finance_inserted,
        "financeTransactionId": finance_row["transaction_id"] if finance_row else None,
        "firestoreSyncStatus": sync_status,
        "firestoreDocument": firestore_path,
        "syncError": sync_error,
    })
    return result
