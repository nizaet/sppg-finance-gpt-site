from __future__ import annotations

import base64
import binascii
import io
import json
import re
import urllib.parse
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader

from backend.accountant_drive import AccountantDriveUploadError, upload_accountant_artifact
from backend.calculator_ai_api import _gemini_key, _gemini_model, _openai_key, _openai_model, _post_json
from backend.db import connection, database_ready

router = APIRouter(tags=["accountant-documents"])

Site = Literal["MAJA", "CEMPLANG"]
InvoiceCategory = Literal[
    "SEWA_MITRA", "TOKEN_LISTRIK", "GAJI_RELAWAN", "SEWA_MOBIL",
    "UPAH", "BAHAN_BAKU", "OPERASIONAL_LAIN",
]
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_BYTES = 16 * 1024 * 1024
APPROVERS = {"MAJA": "EMBUN", "CEMPLANG": "MALIK"}


class DocumentFileIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1)


class InvoicePreviewIn(DocumentFileIn):
    site: Site | None = None
    category: InvoiceCategory | None = None
    accountant_submission_id: int | None = None


class InvoiceLineIn(BaseModel):
    item_name: str = Field(min_length=1, max_length=300)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=80)
    unit_price: float | None = None
    line_total: float | None = None


class DirectInvoiceIn(InvoicePreviewIn):
    site: Site
    category: InvoiceCategory
    invoice_number: str = Field(min_length=1, max_length=180)
    invoice_date: date
    period_start: date | None = None
    period_end: date | None = None
    invoice_amount: float = Field(gt=0)
    lines: list[InvoiceLineIn] = Field(default_factory=list)
    parsed_payload: dict[str, Any] = Field(default_factory=dict)
    parse_confidence: float | None = Field(default=None, ge=0, le=1)
    create_maker: Literal[True] = True
    commit: bool = False


class ApprovalEvidenceIn(DocumentFileIn):
    site: Site | None = None
    parsed_payload: dict[str, Any] | None = None
    commit: bool = False


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _decode(payload: DocumentFileIn) -> tuple[bytes, str]:
    mime = payload.mime_type.lower().strip()
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, "dokumen harus PDF/JPG/PNG/WEBP")
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "file base64 tidak valid") from exc
    if not data:
        raise HTTPException(400, "file kosong")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "file maksimal 16 MB")
    return data, mime


def _safe_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    return (re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .") or "dokumen")[:160]


def _pdf_text(data: bytes) -> str:
    try:
        pages = PdfReader(io.BytesIO(data)).pages
        return "\n\n".join((page.extract_text() or "") for page in pages).strip()
    except Exception:
        return ""


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = re.sub(r"[^0-9,.-]", "", str(value))
    if not raw:
        return None
    if "." in raw and "," not in raw and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    elif "," in raw and "." not in raw and re.fullmatch(r"-?\d{1,3}(,\d{3})+", raw):
        raw = raw.replace(",", "")
    elif "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _iso_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", raw)
    return match.group(0) if match else None


MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
}


def _indonesian_dates(value: str) -> tuple[str | None, str | None, str | None]:
    raw = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    month_pattern = "|".join(MONTHS)
    cross = re.search(
        rf"(\d{{1,2}})\s+({month_pattern})\s*(?:s\.?\s*d\.?|-|–)\s*(\d{{1,2}})\s+({month_pattern})\s+(20\d{{2}})",
        raw,
    )
    if cross:
        year = int(cross.group(5))
        start = date(year, MONTHS[cross.group(2)], int(cross.group(1))).isoformat()
        end = date(year, MONTHS[cross.group(4)], int(cross.group(3))).isoformat()
        return end, start, end
    same = re.search(
        rf"(\d{{1,2}})\s*(?:s\.?\s*d\.?|-|–)\s*(\d{{1,2}})\s+({month_pattern})\s+(20\d{{2}})",
        raw,
    )
    if same:
        year, month = int(same.group(4)), MONTHS[same.group(3)]
        start = date(year, month, int(same.group(1))).isoformat()
        end = date(year, month, int(same.group(2))).isoformat()
        return end, start, end
    single = re.search(rf"(\d{{1,2}})\s+({month_pattern})\s+(20\d{{2}})", raw)
    if single:
        parsed = date(int(single.group(3)), MONTHS[single.group(2)], int(single.group(1))).isoformat()
        return parsed, None, None
    return None, None, None


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _gemini_document(prompt: str, data: bytes, mime: str, extracted_text: str) -> dict[str, Any]:
    key = _gemini_key()
    if not key:
        return {}
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if extracted_text:
        parts.append({"text": "TEKS DOKUMEN:\n" + extracted_text[:50000]})
    else:
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(_gemini_model(None))}:generateContent?key={urllib.parse.quote(key)}"
    )
    response = _post_json(url, body, {"Content-Type": "application/json"}, timeout=90)
    raw = response.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
    return _json_object(str(raw or ""))


def _openai_document(prompt: str, data: bytes, mime: str, extracted_text: str) -> dict[str, Any]:
    key = _openai_key()
    if not key:
        return {}
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if extracted_text:
        content.append({"type": "text", "text": "TEKS DOKUMEN:\n" + extracted_text[:50000]})
    else:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", "detail": "high"},
        })
    response = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {
            "model": _openai_model(None), "messages": [{"role": "user", "content": content}],
            "temperature": 0, "response_format": {"type": "json_object"},
        },
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, timeout=90,
    )
    raw = response.get("choices", [{}])[0].get("message", {}).get("content")
    return _json_object(str(raw or ""))


def _document_ai(prompt: str, data: bytes, mime: str, extracted_text: str) -> dict[str, Any]:
    errors: list[HTTPException] = []
    if _gemini_key():
        try:
            parsed = _gemini_document(prompt, data, mime, extracted_text)
            if parsed:
                return parsed
        except HTTPException as exc:
            errors.append(exc)
    if _openai_key():
        try:
            parsed = _openai_document(prompt, data, mime, extracted_text)
            if parsed:
                return parsed
        except HTTPException as exc:
            errors.append(exc)
    if errors:
        raise errors[-1]
    return {}


def _fallback_invoice(text: str) -> dict[str, Any]:
    compact = re.sub(r"[ \t]+", " ", text)
    invoice = re.search(r"Nomor\s+Invoice\s*:?\s*([^\n]+)", compact, re.I)
    category = "OPERASIONAL_LAIN"
    low = compact.lower()
    if "insentif mitra" in low or "sewa mitra" in low: category = "SEWA_MITRA"
    elif "listrik" in low or "token" in low: category = "TOKEN_LISTRIK"
    elif "upah relawan" in low or "gaji relawan" in low: category = "GAJI_RELAWAN"
    elif "sewa 2 mobil" in low or "sewa mobil" in low: category = "SEWA_MOBIL"
    elif "upah" in low: category = "UPAH"
    elif "/bb/" in low or "beras putih" in low: category = "BAHAN_BAKU"
    totals = re.findall(r"(?:TOTAL|Total Pembayaran)\s*(?:Rp)?\s*([\d.,]+)", compact, re.I)
    amount = _number(totals[-1]) if totals else None
    date_match = re.search(r"Tanggal\s*:?\s*([^\n]+)", compact, re.I)
    invoice_date, period_start, period_end = _indonesian_dates(date_match.group(1) if date_match else "")
    site = "CEMPLANG" if any(x in low for x in ("cemplang", "jawilan", "mitra mukti dermawan")) else None
    if any(x in low for x in ("dapur dermawan mentari", "sangiang", "maja")): site = "MAJA"
    return {
        "site": site,
        "category": category,
        "invoice_number": invoice.group(1).strip() if invoice else None,
        "invoice_date": invoice_date,
        "period_start": period_start,
        "period_end": period_end,
        "invoice_amount": amount,
        "lines": [],
        "confidence": 0.45,
        "warnings": ["Sebagian data dibaca dengan parser cadangan; periksa tanggal dan nilai sebelum simpan."],
    }


INVOICE_PROMPT = """Baca invoice Indonesia ini dan keluarkan SATU JSON valid saja.
Schema: {site, category, invoice_number, invoice_date, period_start, period_end, invoice_amount,
lines:[{item_name,quantity,unit,unit_price,line_total}], confidence, warnings}.
Tanggal wajib ISO YYYY-MM-DD. invoice_date adalah tanggal tunggal; bila tertulis rentang, isi period_start dan period_end.
invoice_amount angka rupiah tanpa pemisah. site hanya MAJA atau CEMPLANG bila terbukti dari dokumen.
category hanya: SEWA_MITRA, TOKEN_LISTRIK, GAJI_RELAWAN, SEWA_MOBIL, UPAH, BAHAN_BAKU, OPERASIONAL_LAIN.
Insentif Mitra = SEWA_MITRA. Upah Relawan = GAJI_RELAWAN. Jangan mengarang data yang tidak terlihat."""


def _normalize_invoice(parsed: dict[str, Any], fallback: dict[str, Any], requested_site: str | None, requested_category: str | None) -> dict[str, Any]:
    merged = {**fallback, **{k: v for k, v in parsed.items() if v not in (None, "", [])}}
    lines = []
    for raw in merged.get("lines") or []:
        if not isinstance(raw, dict) or not str(raw.get("item_name") or "").strip():
            continue
        lines.append({
            "item_name": str(raw.get("item_name")).strip(),
            "quantity": _number(raw.get("quantity")),
            "unit": str(raw.get("unit") or "").strip() or None,
            "unit_price": _number(raw.get("unit_price")),
            "line_total": _number(raw.get("line_total")),
        })
    invoice_date = _iso_date(merged.get("invoice_date"))
    period_start = _iso_date(merged.get("period_start"))
    period_end = _iso_date(merged.get("period_end"))
    date_derived_from_period = False
    if not invoice_date and (period_end or period_start):
        invoice_date = period_end or period_start
        date_derived_from_period = True
    warnings_source = parsed.get("warnings") if parsed else fallback.get("warnings")
    return {
        "site": requested_site or (str(merged.get("site") or "").upper() or None),
        "category": requested_category or str(merged.get("category") or "OPERASIONAL_LAIN").upper(),
        "invoiceNumber": str(merged.get("invoice_number") or "").strip() or None,
        "invoiceDate": invoice_date,
        "periodStart": period_start,
        "periodEnd": period_end,
        "dateDerivedFromPeriod": date_derived_from_period,
        "invoiceAmount": _number(merged.get("invoice_amount")),
        "lines": lines,
        "confidence": min(max(float(merged.get("confidence") or 0.5), 0), 1),
        "warnings": [str(x) for x in (warnings_source or []) if str(x).strip()],
    }


@router.post("/accountant-invoices/document-preview")
def preview_invoice_document(payload: InvoicePreviewIn) -> dict[str, Any]:
    data, mime = _decode(payload)
    text = _pdf_text(data) if mime == "application/pdf" else ""
    fallback = _fallback_invoice(text)
    try:
        ai = _document_ai(INVOICE_PROMPT, data, mime, text)
    except HTTPException as exc:
        ai = {}
        fallback["warnings"].append(f"AI dokumen gagal; parser cadangan digunakan: {exc.detail}")
    if not ai and not text:
        raise HTTPException(503, "AI pembaca gambar belum tersedia atau gagal membaca dokumen")
    result = _normalize_invoice(ai, fallback, payload.site, payload.category)
    missing = [label for label, value in (
        ("nomor invoice", result["invoiceNumber"]),
        ("tanggal", result["invoiceDate"] or result["periodStart"]),
        ("nilai", result["invoiceAmount"]),
    ) if not value]
    if missing:
        result["warnings"].append("Perlu dilengkapi: " + ", ".join(missing))
    if result.get("dateDerivedFromPeriod"):
        result["warnings"].append(
            "Dokumen memakai rentang tanggal; tanggal akhir periode digunakan sebagai tanggal pencatatan invoice."
        )
    operational_plan_count = None
    operational_date_confirmed = None
    if result["category"] == "SEWA_MITRA" and result["site"] and result["invoiceDate"]:
        try:
            from backend import accountant_selected_plan_api as selected_plan
            operational_plan_count = len(selected_plan._plan_candidates(result["site"], date.fromisoformat(result["invoiceDate"])))
            operational_date_confirmed = operational_plan_count > 0
            if not operational_date_confirmed:
                result["warnings"].append("Tanggal Sewa Mitra belum ditemukan pada perencanaan Kalkulator yang terisi.")
        except Exception:
            result["warnings"].append("Pengecekan hari operasional Kalkulator belum dapat dijalankan; invoice tetap dapat direview manual.")
    return {
        **result,
        "fileName": _safe_filename(payload.file_name),
        "mimeType": mime,
        "textExtracted": bool(text),
        "accountantSubmissionId": payload.accountant_submission_id,
        "canCommit": not missing and bool(result["site"]),
        "operationalPlanCount": operational_plan_count,
        "operationalDateConfirmed": operational_date_confirmed,
        "raw": ai or fallback,
    }


def _create_maker(cur: Any, invoice_id: int, site: str, amount: float, reference: str, production_cycle_id: int | None = None) -> dict[str, Any]:
    cur.execute("select id,status from bgn_makers where accountant_invoice_id=%s order by id desc limit 1", (invoice_id,))
    existing = cur.fetchone()
    if existing:
        return {"makerId": existing["id"], "makerStatus": existing["status"], "duplicateMaker": True}
    cur.execute(
        """insert into bgn_makers(production_cycle_id,site,reference_number,amount,status,accountant_invoice_id)
           values (%s,%s,%s,%s,'CREATED',%s) returning id,status""",
        (production_cycle_id, site, reference, amount, invoice_id),
    )
    maker = cur.fetchone()
    cur.execute(
        """insert into bgn_approvals(bgn_maker_id,approver_code,status,requested_at,approval_method)
           values (%s,%s,'PENDING',now(),'PENDING') returning id""",
        (maker["id"], APPROVERS[site]),
    )
    return {"makerId": maker["id"], "makerStatus": maker["status"], "approvalId": cur.fetchone()["id"], "duplicateMaker": False}


@router.post("/accountant-invoices/direct-upload")
def upload_direct_invoice(payload: DirectInvoiceIn) -> dict[str, Any]:
    require_db()
    data, mime = _decode(payload)
    preview = {
        "committed": False, "site": payload.site, "category": payload.category,
        "invoiceNumber": payload.invoice_number, "invoiceDate": payload.invoice_date,
        "invoiceAmount": payload.invoice_amount, "willCreateMaker": payload.create_maker,
    }
    if not payload.commit:
        return preview
    production_cycle_id = None
    with connection() as conn:
        with conn.cursor() as cur:
            if payload.accountant_submission_id is not None:
                cur.execute(
                    "select site,status,production_cycle_id from accountant_submissions where id=%s",
                    (payload.accountant_submission_id,),
                )
                submission = cur.fetchone()
                if not submission:
                    raise HTTPException(404, "accountant submission tidak ditemukan")
                if str(submission.get("site") or "").upper() != payload.site:
                    raise HTTPException(409, "site invoice berbeda dengan site submission Excel")
                if str(submission.get("status") or "").upper() != "SENT":
                    raise HTTPException(409, "tandai Excel sebagai SENT sebelum upload invoice bahan baku")
                production_cycle_id = submission.get("production_cycle_id")
            cur.execute(
                """select id,invoice_evidence_uri from accountant_invoices
                   where upper(coalesce(site,''))=%s and lower(trim(coalesce(invoice_number,'')))=lower(trim(%s))
                   order by id desc limit 1""",
                (payload.site, payload.invoice_number),
            )
            duplicate = cur.fetchone()
            if duplicate:
                return {**preview, "committed": True, "duplicate": True, "accountantInvoiceId": duplicate["id"], "invoiceEvidenceUri": duplicate["invoice_evidence_uri"]}
    safe = _safe_filename(payload.file_name)
    filename = f"invoice_{payload.site.lower()}_{payload.category.lower()}_{payload.invoice_date.isoformat()}_{safe}"
    try:
        uploaded = upload_accountant_artifact(
            kind="invoice", filename=filename, data=data, mime_type=mime,
            site=payload.site, bucket="INVOICE",
        )
    except AccountantDriveUploadError as exc:
        raise HTTPException(503, str(exc)[:1500]) from exc
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into accountant_invoices(
                     accountant_submission_id,site,accountant_code,invoice_category,invoice_number,
                     invoice_date,period_start,period_end,invoice_amount,invoice_evidence_uri,received_at,
                     source_type,source_filename,parsed_payload,parse_confidence,updated_at
                   ) values (%s,%s,'DIRECT',%s,%s,%s,%s,%s,%s,%s,now(),
                            case when cast(%s as bigint) is null then 'DIRECT_UPLOAD' else 'EXCEL_RESPONSE' end,%s,%s::jsonb,%s,now())
                   returning id""",
                (payload.accountant_submission_id, payload.site, payload.category, payload.invoice_number,
                 payload.invoice_date, payload.period_start, payload.period_end, payload.invoice_amount,
                 uploaded["driveUri"], payload.accountant_submission_id, safe,
                 json.dumps(payload.parsed_payload, ensure_ascii=False), payload.parse_confidence),
            )
            invoice_id = int(cur.fetchone()["id"])
            for line in payload.lines:
                cur.execute(
                    """insert into accountant_invoice_items(accountant_invoice_id,item_name,quantity,unit,unit_price,line_total)
                       values (%s,%s,%s,%s,%s,%s)""",
                    (invoice_id, line.item_name, line.quantity, line.unit, line.unit_price, line.line_total),
                )
            # All invoices in this workflow must enter the BGN Maker queue.
            maker = _create_maker(
                cur, invoice_id, payload.site, payload.invoice_amount, payload.invoice_number, production_cycle_id
            )
            conn.commit()
    return {
        **preview, "committed": True, "duplicate": False, "accountantInvoiceId": invoice_id,
        "invoiceEvidenceUri": uploaded["driveUri"], "drivePath": uploaded.get("drivePath"), **maker,
    }


@router.get("/accountant-invoices/direct")
def list_direct_invoices(site: str = "") -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select i.id as invoice_id,i.site,i.invoice_category,i.invoice_number,i.invoice_date,
                          i.period_start,i.period_end,i.invoice_amount,i.invoice_evidence_uri,i.source_type,
                          m.id as maker_id,m.status as maker_status,a.status as approval_status,
                          a.evidence_uri as approval_evidence_uri
                   from accountant_invoices i
                   left join bgn_makers m on m.accountant_invoice_id=i.id
                   left join lateral (select * from bgn_approvals x where x.bgn_maker_id=m.id order by x.id desc limit 1) a on true
                   where i.accountant_submission_id is null and (%s='' or upper(i.site)=upper(%s))
                   order by coalesce(i.invoice_date,i.created_at::date) desc,i.id desc limit 250""",
                (site, site),
            )
            rows = cur.fetchall()
    return {"items": rows, "count": len(rows)}


APPROVAL_PROMPT = """Baca bukti status transaksi bank/BGN ini. Satu file dapat berisi banyak transaksi.
Keluarkan SATU JSON: {document_date, transactions:[{reference_number,beneficiary,amount,status,transaction_date}]}.
Ambil semua transaksi. amount angka rupiah tanpa pemisah. status gunakan SUCCESS, PENDING, FAILED, atau UNKNOWN.
reference_number harus mempertahankan nomor invoice/referensi seperti 150/IM/DMM/VIII/2026 bila terlihat. Tanggal ISO YYYY-MM-DD. Jangan mengarang."""


def _maker_candidates(site: str | None) -> list[dict[str, Any]]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select m.id as maker_id,m.site,m.reference_number,m.amount,m.status as maker_status,
                          a.id as approval_id,a.status as approval_status
                   from bgn_makers m
                   left join lateral (select * from bgn_approvals x where x.bgn_maker_id=m.id order by x.id desc limit 1) a on true
                   where (cast(%s as text) is null or upper(m.site)=upper(%s)) order by m.id desc limit 1000""",
                (site, site),
            )
            return [dict(row) for row in cur.fetchall()]


def _ref(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _match_transactions(parsed: dict[str, Any], site: str | None) -> list[dict[str, Any]]:
    makers = _maker_candidates(site)
    output = []
    for raw in parsed.get("transactions") or []:
        if not isinstance(raw, dict):
            continue
        reference = str(raw.get("reference_number") or "").strip()
        amount = _number(raw.get("amount"))
        status = str(raw.get("status") or "UNKNOWN").upper()
        exact = [
            m for m in makers
            if _ref(reference) and _ref(m.get("reference_number"))
            and (
                _ref(reference) == _ref(m.get("reference_number"))
                or _ref(m.get("reference_number")) in _ref(reference)
                or _ref(reference) in _ref(m.get("reference_number"))
            )
        ]
        method, confidence, match = None, 0.0, None
        if len(exact) == 1:
            method, confidence, match = "REFERENCE_EXACT", 1.0, exact[0]
        elif amount is not None:
            amount_hits = [m for m in makers if abs(float(m.get("amount") or 0) - amount) < 0.01]
            if len(amount_hits) == 1:
                method, confidence, match = "AMOUNT_UNIQUE", 0.8, amount_hits[0]
        output.append({
            "referenceNumber": reference or None, "beneficiary": raw.get("beneficiary"),
            "amount": amount, "status": status, "transactionDate": _iso_date(raw.get("transaction_date")),
            "matchedMakerId": match.get("maker_id") if match else None,
            "matchedSite": match.get("site") if match else None,
            "matchedReference": match.get("reference_number") if match else None,
            "currentApprovalStatus": match.get("approval_status") if match else None,
            "matchMethod": method, "matchConfidence": confidence,
            "willApprove": bool(match and status == "SUCCESS" and confidence >= 0.8),
        })
    return output


def _approval_parse(payload: ApprovalEvidenceIn, data: bytes, mime: str) -> dict[str, Any]:
    if payload.parsed_payload:
        return payload.parsed_payload
    text = _pdf_text(data) if mime == "application/pdf" else ""
    parsed = _document_ai(APPROVAL_PROMPT, data, mime, text)
    if not parsed:
        raise HTTPException(503, "AI belum berhasil membaca bukti approval")
    return parsed


@router.post("/approval-evidence/document-preview")
def preview_approval_evidence(payload: ApprovalEvidenceIn) -> dict[str, Any]:
    data, mime = _decode(payload)
    parsed = _approval_parse(payload, data, mime)
    matches = _match_transactions(parsed, payload.site)
    return {
        "committed": False, "fileName": _safe_filename(payload.file_name), "site": payload.site,
        "documentDate": _iso_date(parsed.get("document_date")), "transactions": matches,
        "transactionCount": len(matches), "matchedCount": sum(1 for x in matches if x["matchedMakerId"]),
        "willApproveCount": sum(1 for x in matches if x["willApprove"]), "raw": parsed,
    }


@router.post("/approval-evidence/upload")
def upload_approval_evidence(payload: ApprovalEvidenceIn) -> dict[str, Any]:
    require_db()
    data, mime = _decode(payload)
    parsed = _approval_parse(payload, data, mime)
    matches = _match_transactions(parsed, payload.site)
    if not payload.commit:
        return {"committed": False, "transactions": matches}
    approved = [row for row in matches if row["willApprove"]]
    if not approved:
        raise HTTPException(409, "tidak ada transaksi SUCCESS yang cocok secara aman dengan Maker")
    filename = f"bukti_approval_{(payload.site or 'multi').lower()}_{_safe_filename(payload.file_name)}"
    try:
        uploaded = upload_accountant_artifact(
            kind="approval", filename=filename, data=data, mime_type=mime,
            site=payload.site, bucket="BUKTI_APPROVAL",
        )
    except AccountantDriveUploadError as exc:
        raise HTTPException(503, str(exc)[:1500]) from exc
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into approval_evidence_documents(site,source_filename,evidence_uri,document_date,parsed_payload)
                   values (%s,%s,%s,%s,%s::jsonb) returning id""",
                (payload.site, _safe_filename(payload.file_name), uploaded["driveUri"], _iso_date(parsed.get("document_date")), json.dumps(parsed, ensure_ascii=False)),
            )
            document_id = int(cur.fetchone()["id"])
            for row in approved:
                maker_id = int(row["matchedMakerId"])
                cur.execute("select id from bgn_approvals where bgn_maker_id=%s order by id desc limit 1", (maker_id,))
                approval = cur.fetchone()
                if approval:
                    approval_id = int(approval["id"])
                    cur.execute(
                        """update bgn_approvals set status='APPROVED',approved_at=coalesce(approved_at,now()),
                               rejected_at=null,evidence_uri=%s,evidence_filename=%s,approval_method='EVIDENCE_UPLOAD'
                           where id=%s""",
                        (uploaded["driveUri"], _safe_filename(payload.file_name), approval_id),
                    )
                else:
                    site = str(row.get("matchedSite") or payload.site or "").upper()
                    cur.execute(
                        """insert into bgn_approvals(bgn_maker_id,approver_code,status,requested_at,approved_at,evidence_uri,evidence_filename,approval_method)
                           values (%s,%s,'APPROVED',now(),now(),%s,%s,'EVIDENCE_UPLOAD') returning id""",
                        (maker_id, APPROVERS[site], uploaded["driveUri"], _safe_filename(payload.file_name)),
                    )
                    approval_id = int(cur.fetchone()["id"])
                cur.execute("update bgn_makers set status=case when status='PAID' then status else 'APPROVED' end where id=%s", (maker_id,))
                cur.execute(
                    """insert into approval_evidence_matches(document_id,bgn_maker_id,approval_id,reference_number,amount,match_method,match_confidence)
                       values (%s,%s,%s,%s,%s,%s,%s) on conflict (document_id,bgn_maker_id) do nothing""",
                    (document_id, maker_id, approval_id, row.get("referenceNumber"), row.get("amount"), row.get("matchMethod"), row.get("matchConfidence")),
                )
            conn.commit()
    return {
        "committed": True, "documentId": document_id, "evidenceUri": uploaded["driveUri"],
        "drivePath": uploaded.get("drivePath"), "approvedMakerIds": [x["matchedMakerId"] for x in approved],
        "approvedCount": len(approved), "transactions": matches,
    }
