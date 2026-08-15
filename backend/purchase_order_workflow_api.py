from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready

router = APIRouter(tags=["purchase-order-workflow"])

FINAL_PO_STATUSES = {
    "FINALIZED",
    "SENT",
    "ACKNOWLEDGED",
    "PARTIAL_RECEIVED",
    "RECEIVED",
}

INDONESIAN_WEEKDAYS = (
    "Senin",
    "Selasa",
    "Rabu",
    "Kamis",
    "Jumat",
    "Sabtu",
    "Minggu",
)
INDONESIAN_MONTHS = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def normalize_whatsapp_phone(value: str) -> str:
    """Return a wa.me-compatible number without inventing a missing contact."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D+", "", raw)
    if raw.startswith("+") and digits:
        normalized = digits
    elif digits.startswith("0"):
        normalized = "62" + digits[1:]
    elif digits.startswith("8"):
        normalized = "62" + digits
    else:
        normalized = digits
    if not 10 <= len(normalized) <= 16:
        raise ValueError("nomor WhatsApp harus 10–16 digit dan menyertakan kode negara")
    return normalized


def _format_qty(value: Any) -> str:
    number = Decimal(str(value or 0))
    text = format(number.normalize(), "f")
    if "." in text:
        whole, fraction = text.split(".", 1)
        fraction = fraction.rstrip("0")
        text = whole if not fraction else f"{whole},{fraction}"
    return text


def _format_indonesian_date(value: date | None) -> str:
    if value is None:
        return "-"
    return (
        f"{INDONESIAN_WEEKDAYS[value.weekday()]}, {value.day} "
        f"{INDONESIAN_MONTHS[value.month - 1]} {value.year}"
    )


def format_purchase_order_whatsapp(po: dict[str, Any], vendor_name: str) -> str:
    """Build one canonical text used by both Pusat Kontrol and GPTS."""
    revision = int(po.get("revision_no") or 1)
    po_label = str(po.get("po_code") or "-")
    if revision > 1:
        po_label += f" / Rev {revision}"
    lines = [
        f"🛒 *PO SPPG {str(po.get('site') or '').upper()}*",
        f"👤 *Vendor:* {vendor_name}",
        f"📅 *Untuk:* {_format_indonesian_date(po.get('distribution_date'))}",
        f"🧾 *No. PO:* {po_label}",
        "",
        "📦 *DAFTAR PESANAN*",
        "",
    ]
    included_items = [item for item in (po.get("items") or []) if Decimal(str(item.get("po_qty") or 0)) > 0]
    for index, item in enumerate(included_items, start=1):
        amount = _format_qty(item.get("po_qty"))
        unit = str(item.get("unit") or "").strip()
        lines.extend(
            [
                f"{index}. *{str(item.get('item_name') or '-').strip()}*",
                f"   {amount}{f' {unit}' if unit else ''}",
            ]
        )
    lines.extend(
        [
            "",
            "Mohon dibantu disiapkan sesuai daftar di atas ya Pak. 🙏",
            "Mohon konfirmasi jika ada barang yang kosong atau harganya berubah.",
            "Terima kasih.",
        ]
    )
    return "\n".join(lines)


class VendorWhatsAppUpdateIn(BaseModel):
    whatsapp_phone: str = Field(min_length=1, max_length=40)


@router.post("/reference/vendors/{vendor_code}/whatsapp")
def update_vendor_whatsapp(vendor_code: str, payload: VendorWhatsAppUpdateIn) -> dict[str, Any]:
    require_db()
    vendor = vendor_code.upper().strip()
    try:
        phone = normalize_whatsapp_phone(payload.whatsapp_phone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update entities
                   set metadata=jsonb_set(coalesce(metadata,'{}'::jsonb),'{whatsapp_phone}',to_jsonb(%s::text),true)
                   where code=%s and active=true
                   returning code,name,metadata""",
                (phone, vendor),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "vendor tidak ditemukan")
        conn.commit()
    return {
        "vendorCode": row["code"],
        "vendorName": row["name"],
        "whatsappPhone": phone,
    }


def _load_po(cur, purchase_order_id: int) -> dict[str, Any]:
    cur.execute(
        """select po.*,pc.distribution_date,pc.cooking_at
           from purchase_orders po
           left join production_cycles pc on pc.id=po.production_cycle_id
           where po.id=%s""",
        (purchase_order_id,),
    )
    po = cur.fetchone()
    if not po:
        raise HTTPException(404, "purchase order not found")
    return po


@router.post("/purchase-orders/{purchase_order_id}/finalize")
def finalize_purchase_order(purchase_order_id: int) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            status = str(po.get("status") or "").upper()
            if status in FINAL_PO_STATUSES:
                return {
                    "purchaseOrderId": po["id"],
                    "poCode": po["po_code"],
                    "status": status,
                    "changed": False,
                }
            if status != "DRAFT":
                raise HTTPException(409, f"PO status {status or '-'} tidak dapat difinalkan")
            cur.execute(
                """update purchase_orders
                   set status='FINALIZED',finalized_at=coalesce(finalized_at,now()),updated_at=now()
                   where id=%s returning id,po_code,status,finalized_at""",
                (purchase_order_id,),
            )
            updated = cur.fetchone()
        conn.commit()
    return {
        "purchaseOrderId": updated["id"],
        "poCode": updated["po_code"],
        "status": updated["status"],
        "finalizedAt": updated["finalized_at"],
        "changed": True,
    }


@router.post("/purchase-orders/{purchase_order_id}/mark-sent")
def mark_purchase_order_sent(purchase_order_id: int) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            status = str(po.get("status") or "").upper()
            if status == "DRAFT":
                raise HTTPException(409, "finalkan PO sebelum menandai terkirim")
            if status not in FINAL_PO_STATUSES:
                raise HTTPException(409, f"PO status {status or '-'} tidak dapat ditandai terkirim")
            next_status = "SENT" if status == "FINALIZED" else status
            cur.execute(
                """update purchase_orders
                   set status=%s,sent_at=coalesce(sent_at,now()),updated_at=now()
                   where id=%s returning id,po_code,status,sent_at""",
                (next_status, purchase_order_id),
            )
            updated = cur.fetchone()
        conn.commit()
    return {
        "purchaseOrderId": updated["id"],
        "poCode": updated["po_code"],
        "status": updated["status"],
        "sentAt": updated["sent_at"],
        "changed": po.get("sent_at") is None or next_status != status,
    }


@router.get("/po-whatsapp-preview")
def purchase_order_whatsapp_preview(
    purchase_order_id: int | None = Query(default=None, alias="purchaseOrderId"),
    site: str = "",
    vendor: str = "",
    distribution_date: date | None = Query(default=None, alias="distributionDate"),
) -> dict[str, Any]:
    """Return the saved final PO, canonical WhatsApp text, and registered contact."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            if purchase_order_id is not None:
                po = _load_po(cur, purchase_order_id)
            else:
                if not site.strip() or not vendor.strip() or distribution_date is None:
                    raise HTTPException(400, "provide purchaseOrderId or site + vendor + distributionDate")
                cur.execute(
                    """select po.*,pc.distribution_date,pc.cooking_at
                       from purchase_orders po
                       join production_cycles pc on pc.id=po.production_cycle_id
                       where upper(po.site)=upper(%s)
                         and upper(po.vendor_code)=upper(%s)
                         and pc.distribution_date=%s
                         and upper(po.status)=any(%s)
                       order by po.revision_no desc,po.created_at desc
                       limit 1""",
                    (site.strip(), vendor.strip(), distribution_date, sorted(FINAL_PO_STATUSES)),
                )
                po = cur.fetchone()
                if not po:
                    raise HTTPException(404, "PO final untuk site, vendor, dan tanggal tersebut belum ditemukan")

            status = str(po.get("status") or "").upper()
            if status not in FINAL_PO_STATUSES:
                raise HTTPException(409, "PO masih DRAFT; finalkan setelah semua edit selesai")

            cur.execute(
                """select id,item_code,item_name,planned_qty,po_qty,unit,planning_price,po_price,notes
                   from purchase_order_items
                   where purchase_order_id=%s and coalesce(po_qty,0)>0
                   order by id""",
                (po["id"],),
            )
            po["items"] = cur.fetchall()
            cur.execute("select code,name,metadata from entities where code=%s", (po["vendor_code"],))
            entity = cur.fetchone() or {"code": po["vendor_code"], "name": po["vendor_code"], "metadata": {}}

    metadata = entity.get("metadata") or {}
    phone = str(metadata.get("whatsapp_phone") or "").strip() or None
    message = format_purchase_order_whatsapp(po, str(entity.get("name") or po["vendor_code"]))
    whatsapp_url = f"https://wa.me/{phone}?text=" if phone else None
    return {
        "purchaseOrderId": po["id"],
        "poCode": po["po_code"],
        "revisionNo": po["revision_no"],
        "site": po["site"],
        "vendorCode": po["vendor_code"],
        "vendorName": entity.get("name") or po["vendor_code"],
        "distributionDate": po.get("distribution_date"),
        "status": status,
        "sentAt": po.get("sent_at"),
        "whatsappPhone": phone,
        "whatsappBaseUrl": whatsapp_url,
        "readyToSend": bool(phone and po.get("items")),
        "message": message,
        "items": po["items"],
    }
