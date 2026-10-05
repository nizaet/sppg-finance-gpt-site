"""Private, immutable artwork and operator-entered document numbers/defaults."""
import base64
import binascii
from io import BytesIO
import json
import re

from fastapi import HTTPException
from PIL import Image

ASSET_FIELDS = {"letterheadAssetId": "LETTERHEAD", "stampAssetId": "STAMP", "signatureAssetId": "SIGNATURE", "recipientSignatureAssetId": "RECIPIENT_SIGNATURE"}
PROFILE_FIELDS = {"issuerName", "issuerSubtitle", "issuerAddress", "senderName", "senderCompany", "recipientName", "recipientCompany", "recipientAddress", "bankName", "accountNumber", "accountName", "senderSignatory", "recipientSignatory", "paymentMethod", "assetProfile", "documentProfileKey", *ASSET_FIELDS}


def checked_number(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /._#()\-]{0,99}", value):
        raise ValueError("Nomor wajib diisi manual (maksimal 100 karakter; huruf, angka, spasi, / . _ # ( ) -)")
    return value


def pdf_filename(number):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", number).strip("._")[:100] + ".pdf"


def validate_artwork(encoded):
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "Gambar tidak valid") from exc
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(422, "Ukuran gambar maksimal 5 MB")
    try:
        with Image.open(BytesIO(data)) as image:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(image.format)
            if not mime or image.width * image.height > 16000000:
                raise ValueError("invalid image")
            image.verify()
    except Exception as exc:
        raise HTTPException(422, "Unggah PNG, JPG, atau WebP valid, maksimal 16 megapiksel; PDF/SVG tidak diterima") from exc
    return data, mime


def validate_asset_refs(cur, site, header):
    for field, kind in ASSET_FIELDS.items():
        asset_id = header.get(field)
        if asset_id is None:
            continue
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id <= 0:
            raise HTTPException(422, "Referensi gambar tidak valid")
        cur.execute("select id from generated_document_assets where id=%s and site=%s and asset_kind=%s", (asset_id, site, kind))
        if not cur.fetchone():
            raise HTTPException(422, "Gambar bukan milik dapur ini atau jenisnya tidak sesuai")


def save_profile(cur, site, header, actor):
    profile = header.get("documentProfileKey") or ("YAYASAN" if header.get("assetProfile") == "maja-yayasan" else "KOPERASI")
    if profile not in {"KOPERASI", "YAYASAN"}:
        raise HTTPException(422, "Jenis kop harus KOPERASI atau YAYASAN")
    saved = {key: value for key, value in header.items() if key in PROFILE_FIELDS}
    if any(value is not None and (not isinstance(value, str) or len(value) > 1000) for key, value in saved.items() if key not in ASSET_FIELDS):
        raise HTTPException(422, "Isian identitas kop harus berupa teks, maksimal 1000 karakter")
    saved["documentProfileKey"] = profile
    cur.execute("""insert into generated_document_profiles(site,profile_key,header_payload,updated_by)
                values (%s,%s,%s::jsonb,%s) on conflict(site,profile_key) do update
                set header_payload=excluded.header_payload,updated_by=excluded.updated_by,updated_at=now()""", (site, profile, json.dumps(saved, ensure_ascii=False), actor))
    return profile, saved


def reserve_numbers(cur, document_id, payload):
    numbers = [(checked_number(payload.document_number), "DOCUMENT")]
    if payload.document_type in {"UPAH_RELAWAN", "INSENTIF_GURU_KADER"}:
        numbers += [(checked_number(item.metadata.get("receiptNo")), "RECEIPT") for item in payload.items]
    normalized = [number.casefold() for number, _ in numbers]
    if len(set(normalized)) != len(normalized):
        raise HTTPException(409, "Nomor dokumen/paket dan nomor kuitansi tiap penerima harus berbeda")
    for number in sorted(normalized):
        cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", ("document-number:" + number,))
        cur.execute("select document_id from generated_accountant_document_numbers where normalized_number=%s", (number,))
        existing = cur.fetchone()
        if existing and existing["document_id"] != document_id:
            raise HTTPException(409, "Nomor invoice/kuitansi sudah dipakai, termasuk dalam riwayat dibatalkan. Isi nomor lain.")
    if document_id is not None:
        cur.execute("delete from generated_accountant_document_numbers where document_id=%s", (document_id,))
        for number, kind in numbers:
            cur.execute("insert into generated_accountant_document_numbers(normalized_number,document_id,number_kind) values (%s,%s,%s)", (number.casefold(), document_id, kind))


def load_artwork(cur, document):
    result = {}
    for field, kind in ASSET_FIELDS.items():
        asset_id = document["header"].get(field)
        if asset_id is None:
            continue
        cur.execute("select content from generated_document_assets where id=%s and site=%s and asset_kind=%s", (asset_id, document["site"], kind))
        row = cur.fetchone()
        if not row:
            raise HTTPException(409, "Gambar dokumen tidak tersedia; periksa kop draft sebelum finalisasi")
        result[field] = bytes(row["content"])
    return result
