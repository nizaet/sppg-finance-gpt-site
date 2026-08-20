from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.parse
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.accountant_drive import AccountantDriveUploadError, upload_accountant_artifact
from backend.calculator_ai_api import _gemini_key, _gemini_model, _post_json
from backend.db import connection, database_ready
from backend.vendor_payment_override_api import VendorPaymentEvidenceIn, record_vendor_payment_evidence

router = APIRouter(prefix="/v1/vendor-payments/evidence", tags=["vendor-payment-evidence"])

MAX_EVIDENCE_BYTES = 12 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
PAYMENT_SOURCE_BY_SITE = {
    "MAJA": "Mobile BCA",
    "CEMPLANG": "myBCA",
}


class EvidenceInspectIn(BaseModel):
    vendor_invoice_id: int = Field(gt=0)
    file_name: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=1, max_length=120)
    content_base64: str


class EvidenceCommitIn(EvidenceInspectIn):
    amount: float = Field(gt=0)
    paid_at: datetime | None = None
    reference_number: str | None = Field(default=None, max_length=300)
    beneficiary_name: str | None = Field(default=None, max_length=300)
    beneficiary_account: str | None = Field(default=None, max_length=200)
    source_account: str | None = Field(default=None, max_length=200)
    remarks: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="operator", max_length=100)


def _require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _safe_filename(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return (name or "bukti_transfer")[:160]


def _decode_file(content_base64: str, mime_type: str) -> tuple[bytes, str]:
    mime = str(mime_type or "").lower().strip()
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, "bukti transfer harus JPG/PNG/WEBP/PDF")
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "file bukti transfer base64 tidak valid") from exc
    if not data:
        raise HTTPException(400, "file bukti transfer kosong")
    if len(data) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, "file bukti transfer maksimal 12 MB")
    return data, mime


def _invoice_context(invoice_id: int) -> dict[str, Any]:
    _require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select vi.id as vendor_invoice_id,vi.vendor_code,vi.site,vi.invoice_number,
                       vi.net_amount,vi.payable_status,vi.purchase_order_id,vi.goods_receipt_id,
                       po.po_code,pc.distribution_date
                from vendor_invoices vi
                left join purchase_orders po on po.id=vi.purchase_order_id
                left join production_cycles pc on pc.id=vi.production_cycle_id
                where vi.id=%s
                """,
                (invoice_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "vendor invoice tidak ditemukan")
    return dict(row)


def _clean_json_text(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    raise HTTPException(502, "AI tidak mengembalikan JSON bukti transfer yang valid")


def _inspect_with_gemini(data: bytes, mime: str, invoice: dict[str, Any]) -> dict[str, Any]:
    key = _gemini_key()
    if not key:
        return {
            "amount": None,
            "paid_at": None,
            "beneficiary_name": None,
            "beneficiary_account": None,
            "source_account": None,
            "reference_number": None,
            "remarks": None,
            "confidence": 0,
            "warning": "Gemini belum dikonfigurasi; isi data transfer secara manual.",
        }

    prompt = f"""Baca bukti transfer bank Indonesia ini sebagai bukti pembayaran vendor SPPG.
Konteks invoice: site={invoice.get('site')}, vendor={invoice.get('vendor_code')}, nilai invoice={invoice.get('net_amount')}, invoice={invoice.get('invoice_number') or '-'}, PO={invoice.get('po_code') or '-'}.
Ekstrak data yang benar-benar terlihat. Jangan menebak digit yang tidak terlihat.
Kembalikan JSON SAJA dengan field:
amount (number atau null),
paid_at (ISO 8601 +07:00 atau null),
beneficiary_name (string/null),
beneficiary_account (string/null),
source_account (string/null, boleh masked),
reference_number (string/null; prioritaskan Reference No / nomor referensi bank; bila tidak ada boleh pakai kode transaksi yang paling spesifik),
remarks (string/null),
bank (string/null),
channel_detected (string/null),
confidence (0 sampai 1).
Untuk angka rupiah, contoh 'IDR 4,887,000.00' berarti 4887000. Jangan mencampur nomor rekening dengan nomor referensi."""

    model = _gemini_model(None)
    body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode("ascii")}},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(key)}"
    response = _post_json(url, body, {"Content-Type": "application/json"}, timeout=75)
    text = response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
    if not text:
        raise HTTPException(502, "Gemini tidak mengembalikan hasil pembacaan bukti transfer")
    parsed = _clean_json_text(str(text))
    parsed["provider"] = "gemini"
    parsed["model"] = model
    return parsed


def _inspect_result(invoice: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    site = str(invoice.get("site") or "").upper()
    source = PAYMENT_SOURCE_BY_SITE.get(site, "BCA")
    expected = float(invoice.get("net_amount") or 0)
    amount_raw = parsed.get("amount")
    try:
        amount = float(amount_raw) if amount_raw is not None else None
    except (TypeError, ValueError):
        amount = None
    warnings: list[str] = []
    if parsed.get("warning"):
        warnings.append(str(parsed["warning"]))
    if amount is not None and expected > 0 and abs(amount - expected) > 0.01:
        warnings.append(f"Nominal bukti {amount:.0f} berbeda dari netto invoice {expected:.0f}; cek invoice yang dipilih sebelum simpan.")
    channel = str(parsed.get("channel_detected") or "").strip()
    if channel and source.lower().replace(" ", "") not in channel.lower().replace(" ", ""):
        warnings.append(f"Channel yang terbaca '{channel}', tetapi aturan site {site} menetapkan sumber pembayaran '{source}'. Sumber tetap mengikuti aturan site.")

    reference = parsed.get("reference_number") or parsed.get("transaction_code") or parsed.get("remarks")
    return {
        "vendorInvoiceId": invoice["vendor_invoice_id"],
        "site": site,
        "vendorCode": invoice.get("vendor_code"),
        "invoiceNumber": invoice.get("invoice_number"),
        "poCode": invoice.get("po_code"),
        "invoiceNetAmount": expected,
        "currentPayableStatus": invoice.get("payable_status"),
        "paymentSource": source,
        "paymentSourceRule": "OWNER_CONFIRMED_SITE_RULE",
        "amount": amount if amount is not None else expected,
        "paidAt": parsed.get("paid_at"),
        "referenceNumber": reference,
        "beneficiaryName": parsed.get("beneficiary_name"),
        "beneficiaryAccount": parsed.get("beneficiary_account"),
        "sourceAccount": parsed.get("source_account"),
        "remarks": parsed.get("remarks"),
        "bank": parsed.get("bank") or "BCA",
        "channelDetected": parsed.get("channel_detected"),
        "confidence": parsed.get("confidence"),
        "provider": parsed.get("provider"),
        "model": parsed.get("model"),
        "warnings": warnings,
    }


@router.post("/inspect")
def inspect_vendor_payment_evidence(payload: EvidenceInspectIn) -> dict[str, Any]:
    invoice = _invoice_context(payload.vendor_invoice_id)
    data, mime = _decode_file(payload.content_base64, payload.mime_type)
    parsed = _inspect_with_gemini(data, mime, invoice)
    return _inspect_result(invoice, parsed)


@router.post("/commit")
def commit_vendor_payment_evidence(payload: EvidenceCommitIn) -> dict[str, Any]:
    invoice = _invoice_context(payload.vendor_invoice_id)
    site = str(invoice.get("site") or "").upper()
    vendor = str(invoice.get("vendor_code") or "").upper()
    source = PAYMENT_SOURCE_BY_SITE.get(site, "BCA")
    data, mime = _decode_file(payload.content_base64, payload.mime_type)

    timestamp = (payload.paid_at or datetime.now()).strftime("%Y%m%d_%H%M%S")
    filename = f"bukti_vendor_{site.lower()}_{vendor.lower()}_inv{payload.vendor_invoice_id}_{timestamp}_{_safe_filename(payload.file_name)}"
    try:
        uploaded = upload_accountant_artifact(kind="invoice", filename=filename, data=data, mime_type=mime)
    except AccountantDriveUploadError as exc:
        raise HTTPException(503, str(exc)[:1500]) from exc

    metadata_note = " | ".join(filter(None, [
        payload.note or "",
        f"beneficiary={payload.beneficiary_name}" if payload.beneficiary_name else "",
        f"beneficiary_account={payload.beneficiary_account}" if payload.beneficiary_account else "",
        f"source_account={payload.source_account}" if payload.source_account else "",
        f"remarks={payload.remarks}" if payload.remarks else "",
        f"payment_source_rule={site}:{source}",
    ]))

    record = record_vendor_payment_evidence(VendorPaymentEvidenceIn(
        site=site,
        vendor_code=vendor,
        amount=payload.amount,
        paid_at=payload.paid_at,
        payment_source=source,
        reference_number=(payload.reference_number or "").strip() or None,
        evidence_uri=uploaded["driveUri"],
        source_external_id=(f"bankref:{payload.reference_number.strip()}" if payload.reference_number else None),
        purchase_order_id=invoice.get("purchase_order_id"),
        goods_receipt_id=invoice.get("goods_receipt_id"),
        vendor_invoice_id=payload.vendor_invoice_id,
        note=metadata_note,
        actor=payload.actor,
        commit=True,
    ))
    return {
        **record,
        "evidenceUri": uploaded["driveUri"],
        "driveFolderId": uploaded.get("folderId"),
        "driveAuthMode": uploaded.get("driveAuthMode"),
        "paymentSource": source,
        "referenceNumber": payload.reference_number,
        "beneficiaryName": payload.beneficiary_name,
        "beneficiaryAccount": payload.beneficiary_account,
        "sourceAccount": payload.source_account,
        "remarks": payload.remarks,
    }
