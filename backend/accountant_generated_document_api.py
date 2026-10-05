from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection, database_ready

router = APIRouter(tags=["accountant-generated-documents"])

Site = Literal["MAJA", "CEMPLANG"]
DocumentType = Literal["BAHAN_BAKU", "OPERASIONAL", "INSENTIF_GURU_KADER", "UPAH_RELAWAN"]


class DocumentItemIn(BaseModel):
    item_name: str = Field(min_length=1, max_length=300)
    category_code: str = Field(default="LAIN_LAIN", max_length=100)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=80)
    unit_price: float = Field(ge=0)


class GeneratedDocumentIn(BaseModel):
    site: Site
    document_type: DocumentType
    service_date: date
    items: list[DocumentItemIn] = Field(min_length=1)
    header_payload: dict[str, Any] = Field(default_factory=dict)


def _require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _document_prefix(document_type: str) -> str:
    return {
        "BAHAN_BAKU": "INV-BHN",
        "OPERASIONAL": "INV-OPS",
        "INSENTIF_GURU_KADER": "KWT-GURU",
        "UPAH_RELAWAN": "KWT-REL",
    }[document_type]


def _master_price(payload: Any) -> float:
    if not isinstance(payload, dict):
        return 0.0
    for key in ("price", "unit_price", "unitPrice", "harga", "harga_satuan"):
        value = payload.get(key)
        try:
            if value not in (None, ""):
                return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return 0.0


@router.get("/accountant-documents/master")
def master_items(site: Site) -> dict[str, Any]:
    _require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select record_key, canonical_name, category_code, unit, source_payload
                   from calculator_master_catalog
                  where site=%s and source_type='PRICE' and active=true
                  order by canonical_name""",
                (site,),
            )
            rows = cur.fetchall()
    return {
        "site": site,
        "items": [
            {
                "recordKey": row["record_key"],
                "itemName": row["canonical_name"],
                "category": row.get("category_code") or "LAIN_LAIN",
                "unit": row.get("unit") or "unit",
                "unitPrice": _master_price(row.get("source_payload")),
            }
            for row in rows
        ],
    }


@router.get("/accountant-documents")
def list_documents(site: Site, service_date: date | None = None) -> dict[str, Any]:
    _require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            if service_date:
                cur.execute(
                    """select id,site,document_type,document_number,service_date,status,
                              header_payload,total_amount,created_at,updated_at
                         from generated_accountant_documents
                        where site=%s and service_date=%s
                        order by id desc""",
                    (site, service_date),
                )
            else:
                cur.execute(
                    """select id,site,document_type,document_number,service_date,status,
                              header_payload,total_amount,created_at,updated_at
                         from generated_accountant_documents
                        where site=%s order by id desc limit 100""",
                    (site,),
                )
            docs = cur.fetchall()
            result = []
            for doc in docs:
                cur.execute(
                    """select item_name,category_code,quantity,unit,unit_price,line_total
                         from generated_accountant_document_items
                        where document_id=%s order by id""",
                    (doc["id"],),
                )
                items = cur.fetchall()
                result.append({
                    "id": doc["id"],
                    "site": doc["site"],
                    "documentType": doc["document_type"],
                    "documentNumber": doc["document_number"],
                    "serviceDate": str(doc["service_date"]),
                    "status": doc["status"],
                    "header": doc["header_payload"] or {},
                    "total": float(doc["total_amount"] or 0),
                    "items": [
                        {"itemName": x["item_name"], "category": x["category_code"], "quantity": float(x["quantity"]), "unit": x["unit"], "unitPrice": float(x["unit_price"]), "lineTotal": float(x["line_total"])}
                        for x in items
                    ],
                })
    return {"documents": result}


@router.post("/accountant-documents")
def generate_document(payload: GeneratedDocumentIn) -> dict[str, Any]:
    _require_db()
    total = sum(round(item.quantity * item.unit_price, 2) for item in payload.items)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select count(*) as count
                     from generated_accountant_documents
                    where site=%s and service_date=%s and document_type=%s""",
                (payload.site, payload.service_date, payload.document_type),
            )
            sequence = int(cur.fetchone()["count"] or 0) + 1
            number = f"{_document_prefix(payload.document_type)}-{payload.site}-{payload.service_date.strftime('%Y%m%d')}-{sequence:03d}"
            cur.execute(
                """insert into generated_accountant_documents
                   (site,document_type,document_number,service_date,status,header_payload,total_amount)
                   values (%s,%s,%s,%s,'DRAFT',%s::jsonb,%s)
                   returning id""",
                (payload.site, payload.document_type, number, payload.service_date, __import__("json").dumps(payload.header_payload, ensure_ascii=False), total),
            )
            document_id = int(cur.fetchone()["id"])
            for item in payload.items:
                cur.execute(
                    """insert into generated_accountant_document_items
                       (document_id,item_name,category_code,quantity,unit,unit_price,line_total)
                       values (%s,%s,%s,%s,%s,%s,%s)""",
                    (document_id, item.item_name, item.category_code, item.quantity, item.unit, item.unit_price, round(item.quantity * item.unit_price, 2)),
                )
            conn.commit()
    return {"ok": True, "document": {"id": document_id, "site": payload.site, "documentType": payload.document_type, "documentNumber": number, "serviceDate": str(payload.service_date), "status": "DRAFT", "header": payload.header_payload, "total": total, "items": [{"itemName": x.item_name, "category": x.category_code, "quantity": x.quantity, "unit": x.unit, "unitPrice": x.unit_price, "lineTotal": round(x.quantity * x.unit_price, 2)} for x in payload.items]}}


@router.patch("/accountant-documents/{document_id}/finalize")
def finalize_document(document_id: int) -> dict[str, Any]:
    _require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("update generated_accountant_documents set status='FINAL',updated_at=now() where id=%s returning id,status", (document_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "dokumen tidak ditemukan")
            conn.commit()
    return {"ok": True, "id": row["id"], "status": row["status"]}
