from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Body, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.auth_api import session_role
from backend.db import connection, database_ready
from backend.generated_document_logic import OP_CATEGORIES, category_name, line_amount, merge_final_documents, receipt_number
from backend.generated_document_settings import checked_number, pdf_filename, validate_artwork, validate_asset_refs, save_profile, reserve_numbers, load_artwork
from backend.generated_document_reference import MAJA_OPERATION_ITEMS, MAJA_PROFILES
from backend.document_numbering import claim_number, suggest_number, invoice_fallback
from backend.legacy_payment_reconciliation import legacy_payment_plan, replace_legacy_payments
from backend.payment_package import incentive_default
from backend.delivery_package import ensure_package, document_dates

router = APIRouter(tags=["accountant-generated-documents"])
Site = Literal["MAJA", "CEMPLANG"]
DocumentType = Literal["BAHAN_BAKU", "OPERASIONAL", "INSENTIF_GURU_KADER", "UPAH_RELAWAN", "INSENTIF_MITRA"]


class DeliverySettingsIn(BaseModel):
    settings: dict[str, Any]


def _validate_delivery_settings(settings):
    # Three 5 MiB images grow to ~20 MiB after base64 encoding, plus metadata.
    if len(json.dumps(settings)) > 25 * 1024 * 1024:
        raise HTTPException(422,'Total aset cetak terlalu besar. Maksimal 5 MB per gambar.')
    for key in ('logo','signature','stamp'):
        if settings.get(key):
            validate_artwork(str(settings[key]).split(',',1)[-1])


class DeliveryAnchorIn(BaseModel):
    period: str = Field(pattern=r'^\d{4}(?:-\d{2})?$')
    next_number: int = Field(ge=1, le=1000000000)


@router.get('/accountant-documents/delivery-controls')
def delivery_controls(site: Site, authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    with connection() as conn, conn.cursor() as cur:
        cur.execute('select kind,settings from lpdh_delivery_profiles where site=%s', (site,))
        return {'profiles':{r['kind']:r['settings'] for r in cur.fetchall()}}


@router.put('/accountant-documents/delivery-profiles/{kind}')
def delivery_profile(kind: Literal['PO','SJ','CKL','KUI'], site: Site, payload: DeliverySettingsIn, authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    _validate_delivery_settings(payload.settings)
    with connection() as conn, conn.cursor() as cur:
        cur.execute('''insert into lpdh_delivery_profiles(site,kind,settings) values(%s,%s,%s::jsonb)
          on conflict(site,kind) do update set settings=excluded.settings,updated_at=now()''',(site,kind,json.dumps(payload.settings)))
        conn.commit()
    return {'ok':True}


@router.put('/accountant-documents/delivery-anchors/{kind}')
def delivery_anchor(kind: Literal['PO','SJ','CKL','KUI'], site: Site, payload: DeliveryAnchorIn, authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    if (kind=='KUI' and len(payload.period)!=4) or (kind!='KUI' and len(payload.period)!=7):
        raise HTTPException(422,'Periode kuitansi adalah tahun; dokumen lain tahun-bulan.')
    try: date.fromisoformat(payload.period+'-01' if len(payload.period)==7 else payload.period+'-01-01')
    except ValueError: raise HTTPException(422,'Periode tidak valid')
    with connection() as conn, conn.cursor() as cur:
        cur.execute('select pg_advisory_xact_lock(hashtext(%s))', ('lpdh-delivery:'+site,))
        cur.execute('select value from lpdh_delivery_counters where site=%s and kind=%s and period=%s for update',(site,kind,payload.period))
        current=cur.fetchone()
        if current and payload.next_number<=current['value']:
            raise HTTPException(409,'Nomor awal harus lebih besar dari nomor yang sudah dialokasikan. Paket lama tidak diubah.')
        cur.execute('''insert into lpdh_delivery_counters(site,kind,period,value) values(%s,%s,%s,%s)
          on conflict(site,kind,period) do update set value=excluded.value''',(site,kind,payload.period,payload.next_number-1))
        conn.commit()
    return {'ok':True,'nextNumber':payload.next_number}


@router.post('/accountant-documents/delivery-sync')
def delivery_sync(site: Site, month: str = Query(pattern=r'^\d{4}-\d{2}$'), authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    try:
        start=date.fromisoformat(month+'-01')
        end=date(start.year+(start.month==12),start.month%12+1,1)
    except ValueError:
        raise HTTPException(422,'Bulan tidak valid')
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where site=%s and service_date>=%s and service_date<%s and document_type in ('BAHAN_BAKU','OPERASIONAL') and status='FINAL' order by service_date,id",(site,start,end))
        for row in cur.fetchall(): ensure_package(cur,row)
        cur.execute('''select p.document_id,p.numbers,p.settings,d.* from lpdh_delivery_packages p
          join generated_accountant_documents d on d.id=p.document_id
          where p.site=%s and p.service_date>=%s and p.service_date<%s order by p.service_date,p.document_id''',(site,start,end))
        packages=[]
        for row in cur.fetchall():
            packages.append({'document':_serialize_document(cur,row),'numbers':row['numbers'],'settings':row['settings'],'dates':document_dates(row['service_date'])})
        conn.commit()
    return {'packages':packages}


@router.put('/accountant-documents/{document_id}/delivery-settings')
def delivery_settings(document_id: int, payload: DeliverySettingsIn, authorization: str | None = Header(default=None)):
    role=session_role(authorization)
    _validate_delivery_settings(payload.settings)
    with connection() as conn, conn.cursor() as cur:
        cur.execute('select * from generated_accountant_documents where id=%s for update',(document_id,))
        row=cur.fetchone()
        if not row: raise HTTPException(404,'Invoice tidak ditemukan')
        if role not in {'OWNER',row['site']}: raise HTTPException(403,'akses site tidak diizinkan')
        if row['status']!='FINAL': raise HTTPException(409,'Invoice tidak aktif FINAL')
        cur.execute('update lpdh_delivery_packages set settings=%s::jsonb,updated_at=now() where document_id=%s',(json.dumps(payload.settings),document_id))
        conn.commit()
    return {'ok':True}


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
        if self.document_type == 'INSENTIF_MITRA':
            if len(self.items) != 1 or self.items[0].quantity != 1 or self.header_payload.get('documentProfileKey') != 'YAYASAN':
                raise ValueError('Invoice Mitra memakai kop Yayasan dan satu nilai insentif harian.')
        if any(isinstance(value, str) and len(value) > 1000 for value in self.header_payload.values()):
            raise ValueError("Isian kop/alamat/bukti maksimal 1000 karakter per kolom")
        for item in self.items:
            if not item.item_name.strip() or not item.unit.strip():
                raise ValueError("Nama item/penerima dan satuan wajib diisi")
            if self.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"} and item.quantity != 1:
                raise ValueError("Kuitansi dibayar harian: jumlah hari harus 1")
            if self.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"} and item.unit.lower() != "hari":
                raise ValueError("Satuan kuitansi harian harus hari")
            if self.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"} and self.header_payload.get("paymentSnapshotVersion") != 2:
                item.metadata["receiptNo"] = checked_number(item.metadata.get("receiptNo"))
            if self.document_type == "INSENTIF_GURU_KADER" and item.metadata.get("recipientType") not in {"Guru", "Kader"}:
                raise ValueError("Pilih jenis penerima Guru atau Kader")
            if self.document_type == "OPERASIONAL" and item.category_code not in OP_CATEGORIES:
                raise ValueError("Pilih kategori operasional sesuai kolom C workbook")
        version = self.header_payload.get("paymentSnapshotVersion")
        if self.header_payload.get('combinedPayments'):
            if self.document_type != 'UPAH_RELAWAN' or version != 2 or self.header_payload['combinedPayments'] is not True:
                raise ValueError('Paket pembayaran gabungan harus menggunakan snapshot harian')
            if any(item.metadata.get('recipientType') not in {'Relawan', 'Guru', 'Kader'} for item in self.items):
                raise ValueError('Pilih kelompok Relawan, Guru atau Kader untuk setiap penerima')
        if version not in (None, 2) or isinstance(version, bool):
            raise ValueError("Versi snapshot pembayaran tidak valid")
        if self.document_type == "INSENTIF_GURU_KADER" and version == 2:
            subtype = self.header_payload.get("recipientSubtype")
            if subtype not in {"Guru", "Kader"} or any(item.metadata.get("recipientType") != subtype for item in self.items):
                raise ValueError("Paket Guru dan Kader harus terpisah; semua penerima wajib sesuai jenis paket")
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


class FinalizeDocumentIn(BaseModel):
    replace_legacy_snapshot: str | None = Field(default=None, min_length=64, max_length=64)


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
            "driveUri": row.get("drive_uri"), "driveExcelUri": row.get("drive_excel_uri"), "driveUploadStatus": row.get("drive_upload_status"),
            "driveUploadError": row.get("drive_upload_error"), "cancelledAt": row.get("cancelled_at"),
            "cancellationReason": row.get("cancellation_reason")}
    cur.execute('select m.id as maker_id,e.accountant_invoice_id from generated_document_maker_exports e left join bgn_makers m on m.accountant_invoice_id=e.accountant_invoice_id where e.document_id=%s', (row['id'],))
    exported = cur.fetchone()
    document['makerId'] = exported['maker_id'] if exported else None
    document['makerInvoiceId'] = exported.get('accountant_invoice_id') if exported else None
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


def _sync_daily(cur, site, service_date, actor, replacement=None):
    daily_lock(cur, site, service_date)
    cur.execute("select data,status from lpdh_daily_state where site=%s and service_date=%s for update", (site, service_date))
    existing = cur.fetchone() or {"data": {}, "status": "DRAFT"}
    docs = load_documents(cur, site, service_date, True)
    try:
        base = existing['data']
        if replacement:
            document, snapshot_hash = replacement
            base = replace_legacy_payments(base, document, snapshot_hash, actor)
        data = merge_final_documents(base, docs)
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
    for field, kind in (("schools", "Guru"), ("posyandu", "Kader")):
        if data.get(field):
            recipients = [recipient for recipient in recipients if recipient['recipientType'] != kind]
        recipients.extend({"name": x["picName"], "recipientType": kind, "unitName": x.get("name") or "", **incentive_default(x, kind)}
                          for x in data.get(field) or [] if x.get("picName") and str(x.get("status") or "Aktif").lower() != "nonaktif")
    grouped_recipients = {}
    for recipient in recipients:
        key = (recipient['name'].strip().casefold(), recipient['recipientType'])
        if key not in grouped_recipients:
            grouped_recipients[key] = dict(recipient)
        else:
            target = grouped_recipients[key]
            target['unitName'] = '; '.join(filter(None,[target.get('unitName'),recipient.get('unitName')]))
            target['dailyAmount'] = float(target.get('dailyAmount') or 0) + float(recipient.get('dailyAmount') or 0)
            target['targetPm'] = float(target.get('targetPm') or 0) + float(recipient.get('targetPm') or 0)
    recipients = list(grouped_recipients.values())
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


@router.get("/accountant-documents/number-suggestion")
def number_suggestion(site: Site, document_type: DocumentType,
                      service_date: date, authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select data from lpdh_site_state where site=%s", (site,))
        data = (cur.fetchone() or {}).get("data") or {}
        return {"documentNumber": suggest_number(cur, site, document_type, invoice_fallback(data, site, document_type, service_date))}


@router.get("/accountant-documents/previous-routine")
def previous_routine(site: Site, service_date: date, source_date: date | None = None,
                     authorization: str | None = Header(default=None)):
    _authorize(authorization, site)
    if source_date and source_date >= service_date:
        raise HTTPException(422, "Pilih tanggal sumber sebelum tanggal pelayanan aktif")
    from backend.document_routine_copy import routine_documents, routine_daily
    from backend.document_numbering import daily_number
    with connection() as conn, conn.cursor() as cur:
        if not source_date:
            cur.execute("""select max(d.service_date) as source_date from (
                select service_date from lpdh_daily_state where site=%s and service_date<%s
                union select service_date from generated_accountant_documents
                  where site=%s and service_date<%s and status<>'CANCELLED'
                ) d left join lpdh_effective_days e on e.site=%s and e.service_date=d.service_date
                where coalesce(e.is_effective,extract(isodow from d.service_date) between 1 and 5)""",
                (site, service_date, site, service_date, site))
            source_date = (cur.fetchone() or {}).get('source_date')
        if not source_date:
            raise HTTPException(404, "Belum ada data hari pelayanan sebelumnya di dapur ini")
        templates = routine_documents(load_documents(cur, site, source_date))
        cur.execute("select data from lpdh_daily_state where site=%s and service_date=%s", (site, source_date))
        source_daily = cur.fetchone()
        cur.execute("select data from lpdh_site_state where site=%s", (site,))
        masters = (cur.fetchone() or {}).get('data') or {}
        cur.execute("select data,status,revision from lpdh_daily_state where site=%s and service_date=%s", (site, service_date))
        current = cur.fetchone() or {}
        number = daily_number(cur, site, service_date, masters, (current.get('data') or {}).get('lpdhNumber'))
    return {'site': site, 'serviceDate': service_date, 'sourceDate': source_date,
            'templates': templates, 'hasDaily': source_daily is not None,
            'dailyDefaults': routine_daily((source_daily or {}).get('data') or {}),
            'lpdhNumber': number, 'targetDailyStatus': current.get('status', 'DRAFT'), 'targetDailyRevision': current.get('revision', 0)}


@router.post("/accountant-documents")
def generate_document(payload: GeneratedDocumentIn, authorization: str | None = Header(default=None)):
    role = _authorize(authorization, payload.site)
    if payload.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"} and payload.header_payload.get("paymentSnapshotVersion") != 2:
        raise HTTPException(422, "Kuitansi baru harus menggunakan satu nomor paket dan lampiran penerima")
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
        claim_number(cur, payload.site, payload.document_type, number, "DOC:" + str(row["id"]))
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
        if (row.get("header_payload") or {}).get("paymentSnapshotVersion") != payload.header_payload.get("paymentSnapshotVersion"):
            raise HTTPException(409, "Versi kuitansi historis tidak dapat diubah")
        if bool((row.get('header_payload') or {}).get('combinedPayments')) != bool(payload.header_payload.get('combinedPayments')):
            raise HTTPException(409, 'Cakupan paket pembayaran tersimpan tidak dapat diubah; buat draft baru')
        if (row.get("header_payload") or {}).get("paymentSnapshotVersion") == 2 and row["document_type"] == "INSENTIF_GURU_KADER" and row["header_payload"].get("recipientSubtype") != payload.header_payload.get("recipientSubtype"):
            raise HTTPException(409, "Jenis paket Guru atau Kader yang tersimpan tidak dapat diubah")
        validate_asset_refs(cur, payload.site, payload.header_payload)
        reserve_numbers(cur, document_id, payload)
        claim_number(cur, payload.site, payload.document_type, payload.document_number, "DOC:" + str(document_id))
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
        if row.get("drive_uri") and row.get("drive_excel_uri"):
            return {"driveUri": row["drive_uri"], "driveExcelUri": row["drive_excel_uri"], "driveUploadStatus": "UPLOADED"}
        document = _serialize_document(cur, row)
        pdf_uri, excel_uri, folder = row.get('drive_uri'), row.get('drive_excel_uri'), row.get('drive_folder_id')
        status, error = 'UPLOADED', None
        try:
            # Different invoices can finalize concurrently. Serialize folder
            # creation per kitchen so the month's/day's folders are reusable.
            cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"generated-archive-folders:{row['site']}",))
            from backend.accountant_drive import upload_accountant_artifact
            from backend.generated_document_pdf import render_document_pdf
            from backend.generated_document_excel import render_document_excel, MIME
            artwork = load_artwork(cur, document)
            if pdf_uri and not folder:
                from backend.google_services import drive_file_parent
                folder = drive_file_parent(pdf_uri)
            key = f"generated-document-{document_id}-"
            if not pdf_uri:
                uploaded = upload_accountant_artifact(kind="invoice", site=row["site"], service_date=document['serviceDate'],
                    target_folder_id=folder, artifact_key=key+'pdf', filename=pdf_filename(document["documentNumber"]),
                    data=render_document_pdf(document, artwork), mime_type="application/pdf")
                pdf_uri, folder = uploaded['driveUri'], uploaded['folderId']
            if not excel_uri:
                uploaded = upload_accountant_artifact(kind="invoice", site=row["site"], service_date=document['serviceDate'],
                    target_folder_id=folder, artifact_key=key+'xlsx', filename=pdf_filename(document["documentNumber"])[:-4]+'.xlsx',
                    data=render_document_excel(document, artwork), mime_type=MIME)
                excel_uri = uploaded['driveUri']
        except Exception:
            status = 'PARTIAL' if pdf_uri or excel_uri else 'FAILED'
            error = "Dokumen tetap FINAL di aplikasi, tetapi arsip PDF dan Excel di Drive belum lengkap. Klik Simpan ke Drive untuk melengkapi; berkas yang berhasil tidak diunggah ulang. Periksa koneksi/izin Drive bila tetap gagal."
        cur.execute("update generated_accountant_documents set drive_uri=%s,drive_excel_uri=%s,drive_folder_id=%s,drive_upload_status=%s,drive_upload_error=%s,updated_at=now() where id=%s", (pdf_uri, excel_uri, folder, status, error, document_id))
        # Complete the evidence after upload, without reopening an issued LPDH.
        if pdf_uri:
            daily_lock(cur, row["site"], row["service_date"])
            cur.execute("select status from lpdh_daily_state where site=%s and service_date=%s for update", (row["site"], row["service_date"]))
            daily_state = cur.fetchone()
            if not daily_state or daily_state["status"] != "GENERATED":
                _sync_daily(cur, row["site"], row["service_date"], role)
        conn.commit()
        return {"driveUri": pdf_uri, "driveExcelUri": excel_uri, "driveUploadStatus": status, "driveUploadError": error}


@router.post("/accountant-documents/{document_id}/archive")
def archive_document(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    return {"ok": True, **_archive_document(document_id, role)}


@router.post('/accountant-documents/{document_id}/export-maker')
def export_document_maker(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, 'database unavailable')
    with connection() as conn, conn.cursor() as cur:
        cur.execute('select * from generated_accountant_documents where id=%s for update', (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, 'Dokumen tidak ditemukan')
        if role not in {'OWNER',row['site']}:
            raise HTTPException(403, 'akses site tidak diizinkan')
        from backend.generated_document_maker import export_snapshot
        result = export_snapshot(cur,_serialize_document(cur,row),role)
        conn.commit()
        return {'ok':True,**result}


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
        cur.execute('select m.status from generated_document_maker_exports e join bgn_makers m on m.accountant_invoice_id=e.accountant_invoice_id where e.document_id=%s', (document_id,))
        maker = cur.fetchone()
        if maker and maker['status'] not in {'CANCELLED','REJECTED'}:
            raise HTTPException(409, 'Dokumen sudah masuk Data Maker. Selesaikan pembatalan pada Data Maker terlebih dahulu agar nominal pending tidak tertinggal.')
        cur.execute('select accountant_invoice_id from generated_document_maker_exports where document_id=%s', (document_id,))
        queued = cur.fetchone()
        if queued and queued.get('accountant_invoice_id'):
            raise HTTPException(409, 'Dokumen masih berada di antrean invoice Pusat Operasional. Hapus alur invoice di sana dahulu, lalu batalkan dokumen LPDH agar tidak ada antrean yang tertinggal.')
        cur.execute("""update generated_accountant_documents set status='CANCELLED',cancelled_at=now(),cancelled_by=%s,
                    cancellation_reason=%s,updated_at=now() where id=%s""", (role, payload.reason.strip(), document_id))
        cur.execute('delete from generated_accountant_document_numbers where document_id=%s', (document_id,))
        cur.execute('delete from document_number_serials where site=%s and namespace=%s and owner_key=%s', (row['site'],row['document_type'],'DOC:'+str(document_id)))
        if row["status"] == "FINAL":
            _sync_daily(cur, row["site"], row["service_date"], role)
        conn.commit()
    return {"ok": True, "id": document_id, "status": "CANCELLED"}


@router.get("/accountant-documents/{document_id}/finalization-check")
def finalization_check(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s", (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if role not in {"OWNER", row['site']}:
            raise HTTPException(403, "akses site tidak diizinkan")
        document = _serialize_document(cur, row)
        cur.execute("select data,status from lpdh_daily_state where site=%s and service_date=%s", (row['site'], row['service_date']))
        existing = cur.fetchone() or {'data':{},'status':'DRAFT'}
        plan = legacy_payment_plan(existing['data'], document) if row['status'] == 'DRAFT' else None
        return {'status':row['status'],'dailyStatus':existing['status'],
                'legacyReplacement':{k:v for k,v in plan.items() if k != 'indexes'} if plan else None}


@router.patch("/accountant-documents/{document_id}/finalize")
def finalize_document(document_id: int, authorization: str | None = Header(default=None), payload: FinalizeDocumentIn | None = Body(default=None)):
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
        replacement = (doc, payload.replace_legacy_snapshot) if payload and payload.replace_legacy_snapshot and row['status'] == 'DRAFT' else None
        cur.execute("update generated_accountant_documents set status='FINAL',finalized_at=coalesce(finalized_at,now()),finalized_by=coalesce(finalized_by,%s),updated_at=now() where id=%s", (role, document_id))
        ensure_package(cur, {**row, 'status':'FINAL'})
        synced = _sync_daily(cur, row["site"], row["service_date"], role, replacement) if replacement else _sync_daily(cur, row["site"], row["service_date"], role)
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


@router.get("/accountant-documents/{document_id}/excel")
def document_excel(document_id: int, authorization: str | None = Header(default=None)):
    role = session_role(authorization)
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from generated_accountant_documents where id=%s", (document_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "dokumen tidak ditemukan")
        if role not in {"OWNER", row['site']}:
            raise HTTPException(403, "akses site tidak diizinkan")
        if row['status'] != 'FINAL':
            raise HTTPException(409, "Excel hanya tersedia untuk dokumen FINAL aktif")
        document = _serialize_document(cur, row)
        artwork = load_artwork(cur, document)
    from backend.generated_document_excel import render_document_excel, MIME
    return {'filename': pdf_filename(document['documentNumber'])[:-4]+'.xlsx', 'mimeType': MIME,
            'contentBase64': base64.b64encode(render_document_excel(document, artwork)).decode()}
