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


@router.post("/vendor-payments/confirm")
def confirm_vendor_payment(payload: VendorPaymentConfirmIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select id,vendor_code,site,net_amount,payable_status,invoice_number
                   from vendor_invoices where id=%s""",
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
                result.update({"committed": True, "duplicate": True, "vendorPaymentId": existing["id"]})
                return result

            cur.execute(
                """insert into vendor_payments(
                     vendor_invoice_id,vendor_code,site,amount,payment_status,payment_source,paid_at,
                     evidence_uri,reference_number,source_key
                   ) values (%s,%s,%s,%s,'PAID',%s,%s,%s,%s,%s) returning id""",
                (
                    invoice["id"], invoice["vendor_code"], invoice["site"], amount,
                    payload.payment_source, payload.paid_at or datetime.now(timezone.utc), payload.evidence_uri,
                    payload.reference_number, key,
                ),
            )
            payment_id = cur.fetchone()["id"]
            cur.execute(
                "update vendor_invoices set payable_status=%s,updated_at=now() where id=%s",
                (new_status, invoice["id"]),
            )
            conn.commit()
            result.update({"committed": True, "duplicate": False, "vendorPaymentId": payment_id})
            return result
