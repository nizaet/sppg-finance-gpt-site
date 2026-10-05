from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.auth_api import session_role
from backend.db import connection, database_ready
from backend.generated_document_logic import OP_CATEGORIES, category_name, line_amount, merge_final_documents, receipt_number
from backend.generated_document_settings import checked_number, pdf_filename, validate_artwork, validate_asset_refs, save_profile, reserve_numbers, load_artwork
from backend.generated_document_reference import MAJA_OPERATION_ITEMS, MAJA_PROFILES

router = APIRouter(tags=["accountant-generated-documents"])
Site = Literal["MAJA", "CEMPLANG"]
DocumentType = Literal["BAHAN_BAKU", "OPERASIONAL", "INSENTIF_GURU_KADER", "UPAH_RELAWAN"]


class DocumentItemIn(BaseModel):
    item_name: str = Field(min_length=1, max_length=300)
    category_code: str = Field(default="Lain-lain", max_length=100)
    quantity: float = Field(gt=0, le=100000000, multiple_of=0.0001, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=80)
    unit_price: float = Field(gt=0, le=100000000000, multiple_of=0.01, allow_inf_nan=False)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratedDocumentIn(BaseModel):
    site: Site
    document_type: DocumentType
    service_date: date
    document_number: str = Field(min_length=1, max_length=100)
    items: list[DocumentItemIn] = Field(min_length=1, max_length=100)
    header_payload: dict[str, Any] = Field(default_factory=dict)
    request_key: str | None = Field(default=None, min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_document(self):
        self.document_number = checked_number(self.document_number)
        if any(isinstance(value, str) and len(value) > 1000 for value in self.header_payload.values()):
            raise ValueError("Isian kop/alamat/bukti maksimal 1000 karakter per kolom")
        for item in self.items:
            if not item.item_name.strip() or not item.unit.strip():
                raise ValueError("Nama item/penerima dan satuan wajib diisi")
            if self.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"} and item.quantity != 1:
                raise ValueError("Kuitansi dibayar harian: jumlah hari harus 1")
            if self.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"} and item.unit.lower() != "hari":
                raise ValueError("Satuan kuitansi harian harus hari")
            if self.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"}:
                item.metadata["receiptNo"] = checked_number(item.metadata.get("receiptNo"))
            if self.document_type == "INSENTIF_GURU_KADER" and item.metadata.get("recipientType") not in {"Guru", "Kader"}:
                raise ValueError("Pilih jenis penerima Guru atau Kader")
            if self.document_type == "OPERASIONAL" and item.category_code not in OP_CATEGORIES:
                raise ValueError("Pilih kategori operasional sesuai kolom C workbook")
        if sum(line_amount(item.quantity, item.unit_price) for item in self.items) >= 1000000000000000:
            raise ValueError("Total dokumen melebihi batas nilai yang dapat disimpan")
        if any(not str(self.header_payload.get(key) or "").strip() for key in ("issuerName", "recipientName", "recipientAddress", "senderSignatory")):
            raise ValueError("Lengkapi kop, nama/alamat penerima, dan nama penandatangan")
        evidence = str(self.header_payload.get("evidenceLink") or "").strip()
        if evidence and not evidence.startswith("https://"):
            raise ValueError("Link bukti harus menggunakan https://")
        return self


class DailySyncIn(BaseModel):
    site: Site
    service_date: date


class CancelDocumentIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class DocumentAssetIn(BaseModel):
    site: Site
    asset_kind: Literal["LETTERHEAD", "STAMP", "SIGNATURE", "RECIPIENT_SIGNATURE"]
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=7000000)


class DocumentProfileIn(BaseModel):
    site: Site
    header_payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_header(self):
        if len(self.header_payload) > 40 or any(isinstance(value, str) and len(value) > 1000 for value in self.header_payload.values()):
            raise ValueError("Isian kop maksimal 1000 karakter per kolom")
        return self


def _authorize(authorization, site):
    role = session_role(authorization)
    if role not in {"OWNER", site}:
        raise HTTPException(403, "akses site tidak diizinkan")
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    return role


def _master_price(payload):
    for key in ("price", "unit_price", "unitPrice", "harga", "harga_satuan"):
        try:
            value = float((payload or {}).get(key) or 0)
            if value > 0:
                return value
        except (ValueError, TypeError):
            pass
    return 0


def _serialize_document(cur, row):
    cur.execute("select item_name,category_code,quantity,unit,unit_price,line_total,item_payload from generated_accountant_document_items where document_id=%s order by id", (row["id"],))
    items = [{"itemName": x["item_name"], "category": x["category_code"], "quantity": float(x["quantity"]),
              "unit": x["unit"], "unitPrice": float(x["unit_price"]), "lineTotal": float(x["line_total"]),
              "metadata": x.get("item_payload") or {}} for x in cur.fetchall()]
    document = {"id": row["id"], "site": row["site"], "documentType": row["document_type"],
            "documentNumber": row["document_number"], "serviceDate": str(row["service_date"]),
            "status": row["status"], "header": row["header_payload"] or {},
            "total": float(row["total_amount"]), "items": items, "finalizedAt": row.get("finalized_at"),
            "driveUri": row.get("drive_uri"), "driveUploadStatus": row.get("drive_upload_status"),
            "driveUploadError": row.get("drive_upload_error"), "cancelledAt": row.get("cancelled_at"),
            "cancellationReason": row.get("cancellation_reason")}
    if row["document_type"] in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"}:
        for index, item in enumerate(items):
            item["metadata"] = {**item["metadata"], "receiptNo": receipt_number(document, index)}
    return document


def load_documents(cur, site, service_date, final_only=False):
    sql = "select * from generated_accountant_documents where site=%s and service_date=%s"
    if final_only:
        sql += " and status='FINAL'"
    cur.execute(sql + " order by id", (site, service_date))
    return [_serialize_document(cur, row) for row in cur.fetchall()]


def daily_lock(cur, site, service_date):
    cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"lpdh-daily:{site}:{service_date}",))


def _sync_daily(cur, site, service_date, actor):
    daily_lock(cur, site, service_date)
    cur.execute("select data,status from lpdh_daily_state where site=%s and service_date=%s for update", (site, service_date))
    existing = cur.fetchone() or {"data": {}, "status": "DRAFT"}
    docs = load_documents(cur, site, service_date, True)
    try:
        data = merge_final_documents(existing["data"], docs)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if data == existing["data"]:
        return {"data": data, "imported": len(docs)}
    if existing["status"] == "GENERATED":
        raise HTTPException(409, "LPDH tanggal ini sudah digenerate. Buka dan simpan sebagai draft sebelum menambah atau membatalkan dokumen final.")
    cur.execute("""insert into lpdh_daily_state(site,service_date,data,status,revision,updated_by,updated_at)
                values (%s,%s,%s::jsonb,'DRAFT',1,%s,now()) on conflict (site,service_date) do update
                set data=excluded.data,status='DRAFT',revision=lpdh_daily_state.revision+1,
                    updated_by=excluded.updated_by,updated_at=now()""", (site, service_date, json.dumps(data, ensure_ascii=False), actor))
    return {"data": data, "imported": len(docs)}


@router.get("/accountant-documents/master")
def master_items(site: Site, authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select data from lpdh_site_state where site=%s", (site,))
        data = (cur.fetchone() or {}).get("data") or {}
        cur.execute("""select record_key,canonical_name,category_code,unit,source_payload from calculator_master_catalog
                    where site=%s and source_type='PRICE' and active=true order by canonical_name""", (site,))
        catalog = cur.fetchall()
        cur.execute("select profile_key,header_payload from generated_document_profiles where site=%s", (site,))
        saved_profiles = {x["profile_key"]: x["header_payload"] for x in cur.fetchall()}
    ops = [{"recordKey": x.get("code") or f"op-{i}", "itemName": x.get("name") or "",
            "category": category_name(x.get("category"), x.get("name")), "unit": x.get("unit") or "unit",
            "unitPrice": float(x.get("defaultPrice") or 0), "kind": "OPERASIONAL"}
           for i, x in enumerate(data.get("operations") or []) if str(x.get("status") or "Aktif").lower() != "nonaktif"]
    if site == "MAJA":
        names = {x["itemName"].casefold() for x in ops}
        ops += [{"recordKey": f"maja-op-{i}", "itemName": name, "category": category_name(category),
                 "unit": unit, "unitPrice": price, "kind": "OPERASIONAL", "referencePrice": True}
                for i, (name, category, unit, price) in enumerate(MAJA_OPERATION_ITEMS) if name.casefold() not in names]
    op_names = {x["itemName"].casefold() for x in ops}
    raw = [{"recordKey": x["record_key"], "itemName": x["canonical_name"], "category": x.get("category_code") or "Bahan baku",
            "unit": x.get("unit") or "unit", "unitPrice": _master_price(x.get("source_payload")), "kind": "BAHAN_BAKU"}
           for x in catalog if x["canonical_name"].casefold() not in op_names]
    profiles = data.get("documentProfiles") or (MAJA_PROFILES if site == "MAJA" else {})
    if not profiles:
        profiles = {"KOPERASI": {"issuerName": data.get("vendor", {}).get("name") or "", "issuerAddress": data.get("vendor", {}).get("address") or "",
                    "recipientName": data.get("identity", {}).get("sppgName") or "", "recipientAddress": "",
                    "senderSignatory": data.get("vendor", {}).get("signatoryName") or "", "paymentMethod": "Transfer"}}
    profiles = {**profiles, **saved_profiles}
    recipients = [{"name": x.get("picName") or "", "recipientType": "Kader" if x.get("picType") in {"3B", "Posyandu", "Kader"} or x.get("unitType") == "Posyandu" or x.get("groupCode") in {"KS-07", "KS-08", "KS-09"} else "Guru",
                   "unitName": x.get("unitName") or x.get("name") or ""}
                  for x in data.get("beneficiaries") or [] if x.get("picName") and str(x.get("status") or "Aktif").lower() != "nonaktif"]
    return {"site": site, "items": raw + ops, "categories": OP_CATEGORIES, "profiles": profiles,
            "volunteers": [x for x in data.get("volunteers") or [] if str(x.get("status") or "Aktif").lower() != "nonaktif"], "recipients": recipients}


@router.post("/accountant-documents/assets")
def upload_document_asset(payload: DocumentAssetIn, authorization: str | None = Header(default=None)):
    role = _authorize(authorization, payload.site)
    data, mime = validate_artwork(payload.content_base64)
    filename = payload.filename.replace("\\", "/").split("/")[-1] or "gambar"
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""insert into generated_document_assets(site,asset_kind,filename,mime_type,content,created_by)
                    values (%s,%s,%s,%s,%s,%s) returning id""", (payload.site, payload.asset_kind, filename, mime, data, role))
        asset_id = cur.fetchone()["id"]
        conn.commit()
    return {"ok": True, "id": asset_id, "filename": filename, "mimeType": mime}


@router.get("/accountant-documents/assets/{asset_id}")
def document_asset(asset_id: int, response: Response, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select site,filename,mime_type,content from generated_document_assets where id=%s", (asset_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "gambar tidak ditemukan")
        if role not in {"OWNER", row["site"]}:
            raise HTTPException(403, "akses site tidak diizinkan")
    response.headers["Cache-Control"] = "private, no-store"
    return {"id": asset_id, "filename": row["filename"], "mimeType": row["mime_type"], "contentBase64": base64.b64encode(bytes(row["content"])).decode()}


@router.put("/accountant-documents/profile")
def save_document_profile(payload: DocumentProfileIn, authorization: str | None = Header(default=None)):
    role = _authorize(authorization, payload.site)
    with connection() as conn, conn.cursor() as cur:
        validate_asset_refs(cur, payload.site, payload.header_payload)
        profile, header = save_profile(cur, payload.site, payload.header_payload, role)
        conn.commit()
    return {"ok": True, "profile": profile, "header": header}


@router.get("/accountant-documents")
def list_documents(site: Site, service_date: date, authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    with connection() as conn, conn.cursor() as cur:
        return {"documents": load_documents(cur, site, service_date)}


def _save_items(cur, document_id, payload):
    for item in payload.items:
        cur.execute("""insert into generated_accountant_document_items
                    (document_id,item_name,category_code,quantity,unit,unit_price,line_total,item_payload)
                    values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (document_id, item.item_name.strip(), item.category_code, item.quantity, item.unit.strip(), item.unit_price,
                     line_amount(item.quantity, item.unit_price), json.dumps(item.metadata, ensure_ascii=False)))


@router.post("/accountant-documents")
def generate_document(payload: GeneratedDocumentIn, authorization: str | None = Header(default=None)):
    role = _authorize(authorization, payload.site)
    digest = hashlib.sha256(json.dumps(payload.model_dump(mode="json", exclude={"request_key"}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with connection() as conn, conn.cursor() as cur:
        if payload.request_key:
            cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (payload.request_key,))
            cur.execute("select * from generated_accountant_documents where request_key=%s", (payload.request_key,))
            row = cur.fetchone()
            if row:
                if row["site"] != payload.site or row["request_hash"] != digest:
                    raise HTTPException(409, "Permintaan sebelumnya sudah tersimpan. Refresh register sebelum membuat dokumen berbeda.")
                return {"ok": True, "document": _serialize_document(cur, row)}
        validate_asset_refs(cur, payload.site, payload.header_payload)
        reserve_numbers(cur, None, payload)
        number = payload.document_number
        total = sum(line_amount(x.quantity, x.unit_price) for x in payload.items)
        cur.execute("""insert into generated_accountant_documents
                    (site,document_type,document_number,service_date,header_payload,total_amount,request_key,request_hash)
                    values (%s,%s,%s,%s,%s::jsonb,%s,%s,%s) returning *""",
                    (payload.site, payload.document_type, number, payload.service_date, json.dumps(payload.header_payload, ensure_ascii=False), total, payload.request_key, digest))
        row = cur.fetchone()
        reserve_numbers(cur, row["id"], payload)
        _save_items(cur, row["id"], payload)
        save_profile(cur, payload.site, payload.header_payload, role)
        document = _serialize_document(cur, row)
        conn.commit()
    return {"ok": True, "document": document}


@router.put("/accountant-documents/{document_id}")
def edit_document(document_id: int, payload: GeneratedDocumentIn, authorization: str | None = Header(default=None)):
    role = _authorize(authorization, payload.site)
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s for update", (document_id,))
        row = cur.fetchone()
        if not row or row["site"] != payload.site:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if row["status"] != "DRAFT" or row["document_type"] != payload.document_type or row["service_date"] != payload.service_date:
            raise HTTPException(409, "Hanya isi draft yang dapat diedit. Site, jenis, tanggal, dan dokumen final terkunci.")
        validate_asset_refs(cur, payload.site, payload.header_payload)
        reserve_numbers(cur, document_id, payload)
        cur.execute("delete from generated_accountant_document_items where document_id=%s", (document_id,))
        _save_items(cur, document_id, payload)
        total = sum(line_amount(x.quantity, x.unit_price) for x in payload.items)
        cur.execute("update generated_accountant_documents set document_number=%s,header_payload=%s::jsonb,total_amount=%s,updated_at=now() where id=%s returning *", (payload.document_number, json.dumps(payload.header_payload, ensure_ascii=False), total, document_id))
        document = _serialize_document(cur, cur.fetchone())
        save_profile(cur, payload.site, payload.header_payload, role)
        conn.commit()
    return {"ok": True, "document": document}


@router.get("/accountant-documents/calendar")
def document_calendar(site: Site, month: str = Query(pattern=r"^\d{4}-\d{2}$"), authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    try:
        start = date.fromisoformat(month + "-01")
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    except ValueError as exc:
        raise HTTPException(422, "Bulan tidak valid") from exc
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""select service_date,status,count(*) as count,sum(total_amount) as total
                    from generated_accountant_documents where site=%s and service_date>=%s and service_date<%s
                    group by service_date,status order by service_date,status""", (site, start, end))
        rows = cur.fetchall()
    days = {}
    for row in rows:
        key = str(row["service_date"])
        item = days.setdefault(key, {"serviceDate": key, "draft": 0, "final": 0, "cancelled": 0, "finalTotal": 0})
        item[{"DRAFT": "draft", "FINAL": "final", "CANCELLED": "cancelled"}[row["status"]]] = int(row["count"])
        if row["status"] == "FINAL":
            item["finalTotal"] = float(row["total"] or 0)
    return {"site": site, "month": month, "items": list(days.values())}


def _archive_document(document_id, role):
    """Use the existing accountant Drive archive, not the payment/maker ledger.

    The row lock serializes normal retries and cancellation. A Drive failure never
    undoes a committed final/daily transaction and is visible with a retry action.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s for update", (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if role not in {"OWNER", row["site"]}:
            raise HTTPException(403, "akses site tidak diizinkan")
        if row["status"] != "FINAL":
            raise HTTPException(409, "Hanya dokumen FINAL aktif yang dapat diarsipkan")
        if row.get("drive_uri"):
            return {"driveUri": row["drive_uri"], "driveUploadStatus": "UPLOADED"}
        document = _serialize_document(cur, row)
        try:
            from backend.accountant_drive import upload_accountant_artifact
            from backend.generated_document_pdf import render_document_pdf
            uploaded = upload_accountant_artifact(kind="invoice", site=row["site"], bucket="INVOICE",
                filename=pdf_filename(document["documentNumber"]), data=render_document_pdf(document, load_artwork(cur, document)), mime_type="application/pdf")
        except Exception:
            error = "PDF final sudah tersimpan di aplikasi, tetapi upload SPPG Drive gagal. Coba Simpan ke Drive lagi; bila tetap gagal periksa koneksi/izin Drive backend."
            cur.execute("update generated_accountant_documents set drive_upload_status='FAILED',drive_upload_error=%s,updated_at=now() where id=%s", (error, document_id))
            conn.commit()
            return {"driveUploadStatus": "FAILED", "driveUploadError": error}
        cur.execute("update generated_accountant_documents set drive_uri=%s,drive_upload_status='UPLOADED',drive_upload_error=null,updated_at=now() where id=%s", (uploaded["driveUri"], document_id))
        conn.commit()
        return {"driveUri": uploaded["driveUri"], "driveUploadStatus": "UPLOADED"}


@router.post("/accountant-documents/{document_id}/archive")
def archive_document(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    return {"ok": True, **_archive_document(document_id, role)}


@router.patch("/accountant-documents/{document_id}/cancel")
def cancel_document(document_id: int, payload: CancelDocumentIn, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not payload.reason.strip() or len(payload.reason.strip()) < 3:
        raise HTTPException(422, "Alasan pembatalan wajib diisi (minimal 3 karakter)")
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s for update", (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if role not in {"OWNER", row["site"]}:
            raise HTTPException(403, "akses site tidak diizinkan")
        if row["status"] == "CANCELLED":
            return {"ok": True, "id": document_id, "status": "CANCELLED"}
        cur.execute("""update generated_accountant_documents set status='CANCELLED',cancelled_at=now(),cancelled_by=%s,
                    cancellation_reason=%s,updated_at=now() where id=%s""", (role, payload.reason.strip(), document_id))
        if row["status"] == "FINAL":
            _sync_daily(cur, row["site"], row["service_date"], role)
        conn.commit()
    return {"ok": True, "id": document_id, "status": "CANCELLED"}


@router.patch("/accountant-documents/{document_id}/finalize")
def finalize_document(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s for update", (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if role not in {"OWNER", row["site"]}:
            raise HTTPException(403, "akses site tidak diizinkan")
        if row["status"] == "CANCELLED":
            raise HTTPException(409, "Dokumen dibatalkan tidak dapat difinalkan kembali. Buat dokumen baru dengan nomor baru.")
        doc = _serialize_document(cur, row)
        try:
            GeneratedDocumentIn(site=doc["site"], document_type=doc["documentType"], service_date=doc["serviceDate"], document_number=doc["documentNumber"],
                                header_payload=doc["header"], items=[{"item_name": x["itemName"], "category_code": x["category"], "quantity": x["quantity"], "unit": x["unit"], "unit_price": x["unitPrice"], "metadata": x["metadata"]} for x in doc["items"]])
        except ValidationError as exc:
            raise HTTPException(422, "Draft belum lengkap. Edit kop, item, kategori, dan tarif harian sebelum finalisasi.") from exc
        validate_asset_refs(cur, doc["site"], doc["header"])
        cur.execute("update generated_accountant_documents set status='FINAL',finalized_at=coalesce(finalized_at,now()),finalized_by=coalesce(finalized_by,%s),updated_at=now() where id=%s", (role, document_id))
        synced = _sync_daily(cur, row["site"], row["service_date"], role)
        conn.commit()
    return {"ok": True, "id": document_id, "status": "FINAL", "syncedToDaily": True, **synced, **_archive_document(document_id, role)}


@router.get("/accountant-documents/{document_id}")
def get_document(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s", (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if role not in {"OWNER", row["site"]}:
            raise HTTPException(403, "akses site tidak diizinkan")
        return {"document": _serialize_document(cur, row)}


@router.post("/accountant-documents/sync-daily")
def sync_daily(payload: DailySyncIn, authorization: str | None = Header(default=None)):
    role = _authorize(authorization, payload.site)
    with connection() as conn, conn.cursor() as cur:
        result = _sync_daily(cur, payload.site, payload.service_date, role)
        conn.commit()
    return {"ok": True, **result}


@router.get("/accountant-documents/{document_id}/pdf")
def document_pdf(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s", (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if role not in {"OWNER", row["site"]}:
            raise HTTPException(403, "akses site tidak diizinkan")
        document = _serialize_document(cur, row)
        artwork = load_artwork(cur, document)
    from backend.generated_document_pdf import render_document_pdf
    content = render_document_pdf(document, artwork)
    return {"filename": pdf_filename(document["documentNumber"]), "mimeType": "application/pdf", "contentBase64": base64.b64encode(content).decode()}
