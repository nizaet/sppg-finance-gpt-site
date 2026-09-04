from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from itertools import combinations
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
CLOSED_PAYABLE = {"PAID", "RECONCILED", "CLOSED", "CANCELLED", "CANCELED"}
logger = logging.getLogger(__name__)


class EvidenceInspectIn(BaseModel):
    vendor_invoice_id: int = Field(gt=0)
    file_name: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=1, max_length=120)
    content_base64: str


class EvidenceCommitIn(EvidenceInspectIn):
    amount: float = Field(gt=0)
    invoice_ids: list[int] | None = Field(default=None, max_length=20)
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


def _raise_commit_failure(exc: Exception) -> None:
    """Keep an unexpected backend failure actionable without leaking credentials.

    A Drive upload or database write can fail after the browser has already
    parsed the proof.  The client must receive a retryable error instead of an
    opaque HTTP 500; the complete traceback remains only in Railway logs.
    """
    reference = uuid.uuid4().hex[:12]
    logger.exception("vendor payment evidence commit failed; reference=%s", reference)
    detail = re.sub(r"(?:postgres(?:ql)?|https?)://[^\s'\"]+", "[redacted-url]", str(exc or "")).strip()
    detail = detail[:500] or type(exc).__name__
    raise HTTPException(
        503,
        f"Pencatatan bukti pembayaran belum selesai (ref {reference}): {type(exc).__name__}: {detail}",
    ) from exc


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
                       po.po_code,pc.distribution_date,vi.created_at
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


def _open_invoice_candidates(invoice: dict[str, Any]) -> list[dict[str, Any]]:
    site = str(invoice.get("site") or "").upper()
    vendor = str(invoice.get("vendor_code") or "").upper()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select vi.id as vendor_invoice_id,vi.invoice_number,vi.net_amount,vi.payable_status,
                       vi.purchase_order_id,vi.goods_receipt_id,po.po_code,pc.distribution_date,vi.created_at,
                       coalesce((select sum(vp.amount) from vendor_payments vp
                         where vp.vendor_invoice_id=vi.id and vp.payment_status in ('PAID','RECONCILED')),0) as paid_total
                from vendor_invoices vi
                left join purchase_orders po on po.id=vi.purchase_order_id
                left join production_cycles pc on pc.id=vi.production_cycle_id
                where upper(vi.site)=upper(%s) and upper(vi.vendor_code)=upper(%s)
                order by vi.created_at desc,vi.id desc limit 20
                """,
                (site, vendor),
            )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("payable_status") or "UNPAID").upper()
        remaining = round(max(float(row.get("net_amount") or 0) - float(row.get("paid_total") or 0), 0.0), 2)
        if status in CLOSED_PAYABLE or remaining <= 0.01:
            continue
        out.append({**dict(row), "remaining_amount": remaining})
    return out


def _detect_invoice_group(invoice: dict[str, Any], amount: float | None) -> dict[str, Any]:
    candidates = _open_invoice_candidates(invoice)
    anchor_id = int(invoice["vendor_invoice_id"])
    target = int(round(float(amount or 0) * 100))
    compact = [
        {
            "vendorInvoiceId": int(row["vendor_invoice_id"]),
            "invoiceNumber": row.get("invoice_number"),
            "poCode": row.get("po_code"),
            "distributionDate": row.get("distribution_date"),
            "netAmount": float(row.get("net_amount") or 0),
            "remainingAmount": float(row.get("remaining_amount") or 0),
        }
        for row in candidates
    ]
    if target <= 0:
        return {"candidateInvoices": compact, "suggestedInvoiceIds": [anchor_id], "suggestedTotal": float(invoice.get("net_amount") or 0), "multiInvoiceDetected": False, "groupAmbiguous": False}

    anchor = next((row for row in candidates if int(row["vendor_invoice_id"]) == anchor_id), None)
    if not anchor:
        return {"candidateInvoices": compact, "suggestedInvoiceIds": [], "suggestedTotal": 0, "multiInvoiceDetected": False, "groupAmbiguous": False}

    anchor_cents = int(round(float(anchor["remaining_amount"]) * 100))
    others = [row for row in candidates if int(row["vendor_invoice_id"]) != anchor_id][:14]
    matches: list[list[dict[str, Any]]] = []
    needed = target - anchor_cents
    if needed == 0:
        matches = [[anchor]]
    elif needed > 0:
        for size in range(1, len(others) + 1):
            for combo in combinations(others, size):
                if sum(int(round(float(row["remaining_amount"]) * 100)) for row in combo) == needed:
                    matches.append([anchor, *combo])
                    if len(matches) >= 8:
                        break
            if matches:
                break
    if not matches:
        return {"candidateInvoices": compact, "suggestedInvoiceIds": [], "suggestedTotal": 0, "multiInvoiceDetected": False, "groupAmbiguous": False}

    best = matches[0]
    ids = [int(row["vendor_invoice_id"]) for row in best]
    total = round(sum(float(row["remaining_amount"]) for row in best), 2)
    return {
        "candidateInvoices": compact,
        "suggestedInvoiceIds": ids if len(matches) == 1 else [],
        "suggestedTotal": total,
        "multiInvoiceDetected": len(best) > 1 and len(matches) == 1,
        "groupAmbiguous": len(matches) > 1,
        "matchingGroupCount": len(matches),
    }


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
Konteks invoice yang diklik: site={invoice.get('site')}, vendor={invoice.get('vendor_code')}, nilai invoice={invoice.get('net_amount')}, invoice={invoice.get('invoice_number') or '-'}, PO={invoice.get('po_code') or '-'}.
Satu transfer BOLEH membayar beberapa invoice vendor sekaligus. Tugas Anda hanya membaca bukti bank, bukan menentukan invoice mana yang dibayar.
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
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
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
    effective_amount = amount if amount is not None else expected
    group = _detect_invoice_group(invoice, effective_amount)

    warnings: list[str] = []
    if parsed.get("warning"):
        warnings.append(str(parsed["warning"]))
    if group.get("multiInvoiceDetected"):
        warnings.append(f"Nominal transfer cocok tepat dengan {len(group['suggestedInvoiceIds'])} invoice {invoice.get('vendor_code')}. Sistem menandai semuanya sebagai satu kelompok transfer.")
    elif group.get("groupAmbiguous"):
        warnings.append("Nominal transfer cocok dengan lebih dari satu kombinasi invoice. Pilih invoice secara manual sebelum simpan.")
    elif amount is not None and expected > 0 and abs(amount - expected) > 0.01:
        warnings.append(f"Nominal bukti {amount:.0f} berbeda dari invoice yang diklik {expected:.0f}; belum ditemukan kombinasi invoice yang pasti.")
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
        "amount": effective_amount,
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
        **group,
        "warnings": warnings,
    }


@router.post("/inspect")
def inspect_vendor_payment_evidence(payload: EvidenceInspectIn) -> dict[str, Any]:
    invoice = _invoice_context(payload.vendor_invoice_id)
    data, mime = _decode_file(payload.content_base64, payload.mime_type)
    parsed = _inspect_with_gemini(data, mime, invoice)
    return _inspect_result(invoice, parsed)


def _selected_allocations(payload: EvidenceCommitIn) -> tuple[list[dict[str, Any]], str, str, float]:
    requested = list(dict.fromkeys(payload.invoice_ids or [payload.vendor_invoice_id]))
    if payload.vendor_invoice_id not in requested:
        requested.insert(0, payload.vendor_invoice_id)
    invoices = [_invoice_context(invoice_id) for invoice_id in requested]
    site = str(invoices[0].get("site") or "").upper()
    vendor = str(invoices[0].get("vendor_code") or "").upper()
    if any(str(row.get("site") or "").upper() != site or str(row.get("vendor_code") or "").upper() != vendor for row in invoices):
        raise HTTPException(409, "satu transfer hanya boleh dialokasikan ke invoice vendor dan site yang sama")

    candidates = {int(row["vendor_invoice_id"]): row for row in _open_invoice_candidates(invoices[0])}
    allocations: list[dict[str, Any]] = []
    for invoice in invoices:
        invoice_id = int(invoice["vendor_invoice_id"])
        candidate = candidates.get(invoice_id)
        if not candidate:
            raise HTTPException(409, f"invoice #{invoice_id} sudah lunas/tertutup atau tidak memiliki sisa tagihan")
        allocations.append({**invoice, "allocation_amount": float(candidate["remaining_amount"])})

    if len(allocations) > 1:
        allocation_total = round(sum(float(row["allocation_amount"]) for row in allocations), 2)
        if float(payload.amount) + 0.01 < allocation_total:
            raise HTTPException(409, f"nominal transfer {float(payload.amount):.0f} lebih kecil dari total invoice terpilih {allocation_total:.0f}")
    else:
        if float(payload.amount) > float(allocations[0]["allocation_amount"]) + 0.01:
            raise HTTPException(409, "nominal transfer melebihi sisa invoice; pilih invoice lain jika ini satu transfer gabungan")
        allocations[0]["allocation_amount"] = float(payload.amount)
    allocation_total = round(sum(float(row["allocation_amount"]) for row in allocations), 2)
    return allocations, site, vendor, round(max(float(payload.amount) - allocation_total, 0), 2)


@router.post("/commit")
def commit_vendor_payment_evidence(payload: EvidenceCommitIn) -> dict[str, Any]:
    try:
        allocations, site, vendor, vendor_credit_amount = _selected_allocations(payload)
        source = PAYMENT_SOURCE_BY_SITE.get(site, "BCA")
        data, mime = _decode_file(payload.content_base64, payload.mime_type)
        paid_at = payload.paid_at or datetime.now(timezone.utc)

        timestamp = paid_at.strftime("%Y%m%d_%H%M%S")
        group_label = f"{len(allocations)}inv" if len(allocations) > 1 else f"inv{allocations[0]['vendor_invoice_id']}"
        filename = f"bukti_vendor_{site.lower()}_{vendor.lower()}_{group_label}_{timestamp}_{_safe_filename(payload.file_name)}"
        uploaded = upload_accountant_artifact(
            kind="invoice", filename=filename, data=data, mime_type=mime,
            site=site, bucket="BUKTI_PEMBAYARAN_VENDOR",
        )
    except AccountantDriveUploadError as exc:
        raise HTTPException(503, str(exc)[:1500]) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _raise_commit_failure(exc)

    try:
        reference = (payload.reference_number or "").strip() or None
        group_key = reference or f"evidence-{timestamp}-{vendor}-{round(float(payload.amount),2)}"
        payment_results: list[dict[str, Any]] = []
        for row in allocations:
            invoice_id = int(row["vendor_invoice_id"])
            allocation_amount = float(row["allocation_amount"])
            metadata_note = " | ".join(filter(None, [
                payload.note or "",
                f"bank_transfer_group={group_key}",
                f"bank_transfer_total={round(float(payload.amount),2)}",
                f"allocation_invoice_id={invoice_id}",
                f"allocation_amount={allocation_amount}",
                f"beneficiary={payload.beneficiary_name}" if payload.beneficiary_name else "",
                f"beneficiary_account={payload.beneficiary_account}" if payload.beneficiary_account else "",
                f"source_account={payload.source_account}" if payload.source_account else "",
                f"remarks={payload.remarks}" if payload.remarks else "",
                f"payment_source_rule={site}:{source}",
            ]))
            result = record_vendor_payment_evidence(VendorPaymentEvidenceIn(
                site=site,
                vendor_code=vendor,
                amount=allocation_amount,
                paid_at=paid_at,
                payment_source=source,
                reference_number=reference,
                evidence_uri=uploaded["driveUri"],
                source_external_id=f"bank-transfer:{group_key}:invoice:{invoice_id}",
                purchase_order_id=row.get("purchase_order_id"),
                goods_receipt_id=row.get("goods_receipt_id"),
                vendor_invoice_id=invoice_id,
                note=metadata_note,
                actor=payload.actor,
                commit=True,
            ))
            payment_results.append({
                "vendorInvoiceId": invoice_id,
                "invoiceNumber": row.get("invoice_number"),
                "allocatedAmount": allocation_amount,
                "vendorPaymentId": result.get("vendorPaymentId"),
                "financeTransactionId": result.get("financeTransactionId"),
                "payableStatusAfter": result.get("payableStatusAfter"),
                "duplicate": result.get("duplicate", False),
            })
        credit_result = None
        if vendor_credit_amount > 0.01:
            credit_result = record_vendor_payment_evidence(VendorPaymentEvidenceIn(
                site=site, vendor_code=vendor, amount=vendor_credit_amount, paid_at=paid_at,
                payment_source=source, reference_number=reference, evidence_uri=uploaded["driveUri"],
                source_external_id=f"bank-transfer:{group_key}:vendor-credit",
                note=" | ".join(filter(None, [payload.note or "", f"bank_transfer_group={group_key}",
                    f"bank_transfer_total={round(float(payload.amount),2)}", f"vendor_credit={vendor_credit_amount}",
                    "kelebihan transfer; saldo kredit vendor belum dialokasikan", payload.remarks or ""])),
                actor=payload.actor, commit=True, force_unreconciled=True,
            ))
    except HTTPException:
        raise
    except Exception as exc:
        _raise_commit_failure(exc)

    return {
        "committed": True,
        "multiInvoice": len(allocations) > 1,
        "invoiceCount": len(allocations),
        "invoiceIds": [int(row["vendor_invoice_id"]) for row in allocations],
        "transferAmount": round(float(payload.amount), 2),
        "allocationTotal": round(sum(float(row["allocation_amount"]) for row in allocations), 2),
        "vendorCreditAmount": vendor_credit_amount,
        "vendorCreditPaymentId": credit_result.get("vendorPaymentId") if credit_result else None,
        "paymentResults": payment_results,
        "evidenceUri": uploaded["driveUri"],
        "driveFolderId": uploaded.get("folderId"),
        "driveAuthMode": uploaded.get("driveAuthMode"),
        "paymentSource": source,
        "referenceNumber": reference,
        "beneficiaryName": payload.beneficiary_name,
        "beneficiaryAccount": payload.beneficiary_account,
        "sourceAccount": payload.source_account,
        "remarks": payload.remarks,
        "payableStatusAfter": "PAID" if all(row.get("payableStatusAfter") == "PAID" for row in payment_results) else "PARTIAL",
    }
