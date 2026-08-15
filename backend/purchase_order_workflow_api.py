from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.stock_opname_parser import canonical_unit

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


class PurchaseOrderEditItemIn(BaseModel):
    item_code: str | None = None
    item_name: str = Field(min_length=1)
    planning_snapshot_item_id: int | None = None
    planned_qty: float | None = None
    po_qty: float = Field(ge=0)
    unit: str | None = None
    planning_price: float | None = Field(default=None, ge=0)
    po_price: float | None = Field(default=None, ge=0)
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None


class PurchaseOrderEditIn(BaseModel):
    vendor_code: str = Field(min_length=1)
    items: list[PurchaseOrderEditItemIn] = Field(min_length=1)


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


def _has_receiving(cur, purchase_order_id: int) -> bool:
    cur.execute("select exists(select 1 from goods_receipts where purchase_order_id=%s) as used", (purchase_order_id,))
    return bool(cur.fetchone()["used"])


@router.patch("/purchase-orders/{purchase_order_id}")
def edit_purchase_order(purchase_order_id: int, payload: PurchaseOrderEditIn) -> dict[str, Any]:
    """Edit only a DRAFT PO; final/sent POs must first become a new revision."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            status = str(po.get("status") or "").upper()
            if status != "DRAFT":
                raise HTTPException(409, "PO final/terkirim tidak boleh ditimpa; gunakan Buat Revisi")
            if _has_receiving(cur, purchase_order_id):
                raise HTTPException(409, "PO yang sudah memiliki penerimaan tidak dapat diedit")
            vendor = payload.vendor_code.upper().strip()
            cur.execute("select code from entities where code=%s and active=true", (vendor,))
            if not cur.fetchone():
                raise HTTPException(404, "vendor tidak ditemukan")
            cur.execute(
                "update purchase_orders set vendor_code=%s,updated_at=now() where id=%s",
                (vendor, purchase_order_id),
            )
            cur.execute("delete from purchase_order_items where purchase_order_id=%s", (purchase_order_id,))
            for item in payload.items:
                cur.execute(
                    """insert into purchase_order_items(
                         purchase_order_id,item_code,item_name,planning_snapshot_item_id,planned_qty,po_qty,unit,
                         planning_price,po_price,item_aliases,notes
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                    (
                        purchase_order_id, item.item_code, item.item_name.strip(), item.planning_snapshot_item_id,
                        item.planned_qty, item.po_qty, canonical_unit(item.unit), item.planning_price,
                        item.po_price, json.dumps(item.aliases, ensure_ascii=False), item.notes,
                    ),
                )
        conn.commit()
    return {
        "purchaseOrderId": purchase_order_id,
        "poCode": po["po_code"],
        "revisionNo": po["revision_no"],
        "status": "DRAFT",
        "vendorCode": vendor,
        "itemCount": len(payload.items),
        "changed": True,
    }


@router.delete("/purchase-orders/{purchase_order_id}")
def delete_draft_purchase_order(purchase_order_id: int) -> dict[str, Any]:
    """Hard-delete only an unsent DRAFT; finalized evidence is cancelled/revised instead."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            if str(po.get("status") or "").upper() != "DRAFT":
                raise HTTPException(409, "Hanya DRAFT yang dapat dihapus permanen; PO final gunakan Batalkan")
            if _has_receiving(cur, purchase_order_id):
                raise HTTPException(409, "PO yang sudah memiliki penerimaan tidak dapat dihapus")
            cur.execute("delete from purchase_order_items where purchase_order_id=%s", (purchase_order_id,))
            cur.execute("delete from purchase_orders where id=%s", (purchase_order_id,))
        conn.commit()
    return {"deleted": True, "purchaseOrderId": purchase_order_id, "poCode": po["po_code"]}


@router.post("/purchase-orders/{purchase_order_id}/revise")
def revise_purchase_order(purchase_order_id: int) -> dict[str, Any]:
    """Create an editable DRAFT revision while preserving the prior final/sent PO."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            status = str(po.get("status") or "").upper()
            if status == "DRAFT":
                return {
                    "purchaseOrderId": po["id"], "poCode": po["po_code"],
                    "revisionNo": po["revision_no"], "status": status, "changed": False,
                }
            if status not in {"FINALIZED", "SENT", "ACKNOWLEDGED"}:
                raise HTTPException(409, f"PO status {status or '-'} tidak dapat direvisi")
            if _has_receiving(cur, purchase_order_id):
                raise HTTPException(409, "PO yang sudah memiliki penerimaan tidak dapat direvisi")
            cur.execute(
                "select id,po_code,revision_no from purchase_orders where supersedes_po_id=%s and status='DRAFT' order by revision_no desc limit 1",
                (purchase_order_id,),
            )
            existing_draft = cur.fetchone()
            if existing_draft:
                return {
                    "purchaseOrderId": existing_draft["id"], "poCode": existing_draft["po_code"],
                    "revisionNo": existing_draft["revision_no"], "status": "DRAFT",
                    "supersedesPurchaseOrderId": purchase_order_id, "changed": False,
                }
            cur.execute("select coalesce(max(revision_no),0)+1 as revision from purchase_orders where po_code=%s", (po["po_code"],))
            revision = int(cur.fetchone()["revision"])
            cur.execute(
                """insert into purchase_orders(
                     po_code,revision_no,production_cycle_id,site,vendor_code,status,supersedes_po_id,
                     source_planning_snapshot_id,source_type,source_external_id,source_uri,source_hash,
                     source_raw_text,historical_import
                   ) values (%s,%s,%s,%s,%s,'DRAFT',%s,%s,%s,%s,%s,null,%s,%s)
                   returning id""",
                (
                    po["po_code"], revision, po["production_cycle_id"], po["site"], po["vendor_code"], po["id"],
                    po.get("source_planning_snapshot_id"), po.get("source_type"), po.get("source_external_id"),
                    po.get("source_uri"), po.get("source_raw_text"), bool(po.get("historical_import")),
                ),
            )
            new_id = cur.fetchone()["id"]
            cur.execute(
                """insert into purchase_order_items(
                     purchase_order_id,item_code,item_name,planning_snapshot_item_id,planned_qty,po_qty,unit,
                     planning_price,po_price,item_aliases,notes)
                   select %s,item_code,item_name,planning_snapshot_item_id,planned_qty,po_qty,unit,
                          planning_price,po_price,item_aliases,notes
                   from purchase_order_items where purchase_order_id=%s""",
                (new_id, purchase_order_id),
            )
        conn.commit()
    return {
        "purchaseOrderId": new_id,
        "poCode": po["po_code"],
        "revisionNo": revision,
        "status": "DRAFT",
        "supersedesPurchaseOrderId": purchase_order_id,
        "changed": True,
    }


@router.post("/purchase-orders/{purchase_order_id}/cancel")
def cancel_purchase_order(purchase_order_id: int) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            po = _load_po(cur, purchase_order_id)
            status = str(po.get("status") or "").upper()
            if status in {"CANCELLED", "SUPERSEDED"}:
                return {"purchaseOrderId": po["id"], "status": status, "changed": False}
            if status in {"PARTIAL_RECEIVED", "RECEIVED"} or _has_receiving(cur, purchase_order_id):
                raise HTTPException(409, "PO yang sudah memiliki penerimaan tidak dapat dibatalkan")
            cur.execute("update purchase_orders set status='CANCELLED',updated_at=now() where id=%s", (purchase_order_id,))
        conn.commit()
    return {"purchaseOrderId": purchase_order_id, "poCode": po["po_code"], "status": "CANCELLED", "changed": True}


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
            if po.get("supersedes_po_id"):
                cur.execute(
                    "update purchase_orders set status='SUPERSEDED',updated_at=now() where id=%s and status in ('FINALIZED','SENT','ACKNOWLEDGED')",
                    (po["supersedes_po_id"],),
                )
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
