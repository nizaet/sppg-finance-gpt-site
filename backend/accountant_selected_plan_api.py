from __future__ import annotations

import base64
import binascii
import io
import re
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend import accountant_excel_api as excel
from backend import calculator_planning_bridge_api as bridge
from backend.accountant_drive import AccountantDriveUploadError, upload_accountant_artifact
from backend.db import connection, database_ready
from backend.item_taxonomy import vendor_for_item

router = APIRouter(tags=["accountant-selected-plan"])

APPROVERS = {"MAJA": "EMBUN", "CEMPLANG": "MALIK"}
MAX_INVOICE_BYTES = 12 * 1024 * 1024
ALLOWED_INVOICE_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _plan_candidates(site: str, distribution_date: date) -> list[dict[str, Any]]:
    _, _, _, candidates = bridge._daily_plan_matches(site, distribution_date)
    return sorted(candidates, key=lambda row: (row["updated_at"], row["item_count"]), reverse=True)


def _plan_option(candidate: dict[str, Any]) -> dict[str, Any]:
    data = candidate["data"]
    shopping_json = data.get("shoppingListJSON") or {}
    grand_total = _safe_float(shopping_json.get("grand_total_num"))
    return {
        "appId": candidate["app_id"],
        "documentId": candidate["doc"].id,
        "planName": data.get("planName") or f"Perencanaan {candidate['doc'].id}",
        "itemCount": candidate["item_count"],
        "updatedAt": _json_safe(candidate["updated_at"]),
        "porsiKecil": _safe_float(data.get("porsiKecil")),
        "porsiBesar": _safe_float(data.get("porsiBesar")),
        "grandTotal": grand_total,
    }


def _select_candidate(site: str, distribution_date: date, document_id: str) -> dict[str, Any]:
    wanted = document_id.strip()
    if not wanted:
        raise HTTPException(400, "calculator_document_id wajib dipilih")
    candidates = _plan_candidates(site, distribution_date)
    for candidate in candidates:
        if candidate["doc"].id == wanted:
            return candidate
    raise HTTPException(404, "perencanaan Kalkulator yang dipilih tidak ditemukan untuk site/tanggal ini")


def _calculator_items(site: str, candidate: dict[str, Any]) -> list[dict[str, Any]]:
    plan = candidate["data"]
    shopping = ((plan.get("shoppingListJSON") or {}).get("shoppingList") or [])
    if not isinstance(shopping, list) or not shopping:
        raise HTTPException(409, "perencanaan dipilih tetapi daftar belanja masih kosong")

    items: list[dict[str, Any]] = []
    for raw in shopping:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("item") or raw.get("name") or "").strip()
        qty = _safe_float(raw.get("jumlah"))
        if not name or qty is None:
            continue
        supplier_key = str(raw.get("supplierOverride") or "").strip()
        category = bridge.SUPPLIER_CATEGORY.get(supplier_key) or str(raw.get("category_code") or "").strip() or None
        unit = str(raw.get("satuan") or "").strip() or None
        preferred_vendor = vendor_for_item(name, category, site, None)
        items.append({
            "item_name": name,
            "planned_qty": qty,
            "unit": unit,
            "planning_price": _safe_float(raw.get("harga_satuan")),
            "preferred_vendor_code": preferred_vendor,
            "category_code": category,
            "notes": str(raw.get("note") or "").strip() or None,
            "source_payload": {
                **_json_safe(raw),
                "calculatorDocumentId": candidate["doc"].id,
                "planName": plan.get("planName"),
            },
        })
    if not items:
        raise HTTPException(409, "perencanaan dipilih tetapi tidak ada item belanja valid")
    return items


def _ensure_cycle(cur: Any, site: str, distribution_date: date) -> int:
    cycle_code = f"{site}-{distribution_date.strftime('%Y%m%d')}"
    cur.execute(
        """
        insert into production_cycles(cycle_code,site,distribution_date,status)
        values (%s,%s,%s,'PLANNING')
        on conflict (cycle_code) do update set site=excluded.site
        returning id
        """,
        (cycle_code, site, distribution_date),
    )
    return int(cur.fetchone()["id"])


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return (text or "planning")[:45]


def _selected_plan_artifact(site: str, distribution_date: date, document_id: str) -> dict[str, Any]:
    candidate = _select_candidate(site, distribution_date, document_id)
    plan = candidate["data"]
    items = _calculator_items(site, candidate)
    snapshot = {
        "id": None,
        "production_cycle_id": None,
        "payload": {
            "porsiKecil": plan.get("porsiKecil"),
            "porsiBesar": plan.get("porsiBesar"),
            "planName": plan.get("planName"),
            "calculatorDocumentId": document_id,
        },
    }
    rows, grand_total, pagu, delta = excel._build_rows(snapshot, items)
    plan_name = str(plan.get("planName") or f"Perencanaan {document_id}")
    filename = f"daftar_belanja_{distribution_date.isoformat()}_{site.lower()}_{_slug(plan_name)}_{document_id[-6:]}.xlsx"
    xlsx = excel._workbook_bytes(rows)
    return {
        "candidate": candidate,
        "planName": plan_name,
        "items": items,
        "rows": rows,
        "grandTotal": grand_total,
        "paguBgn": pagu,
        "paguMinusEstimate": delta,
        "filename": filename,
        "xlsx": xlsx,
    }


class SelectedPlanExcelIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    distribution_date: date
    calculator_document_id: str = Field(min_length=1)
    commit: bool = False


def _selected_download_url(payload: SelectedPlanExcelIn) -> str:
    return "/v1/accountant-excel/download-selected-plan?" + urlencode({
        "site": payload.site,
        "distributionDate": payload.distribution_date.isoformat(),
        "calculatorDocumentId": payload.calculator_document_id,
    })


@router.get("/accountant-excel/planning-options")
def accountant_planning_options(
    site: Literal["MAJA", "CEMPLANG"],
    distribution_date: date = Query(alias="distributionDate"),
) -> dict[str, Any]:
    candidates = _plan_candidates(site, distribution_date)
    return {
        "site": site,
        "distributionDate": distribution_date.isoformat(),
        "count": len(candidates),
        "items": [_plan_option(row) for row in candidates],
        "selectionRequired": len(candidates) > 1,
        "mode": "ONE_CALCULATOR_DOCUMENT_PER_EXCEL",
    }


@router.post("/accountant-excel/from-selected-plan")
def accountant_excel_from_selected_plan(payload: SelectedPlanExcelIn) -> dict[str, Any]:
    require_db()
    artifact = _selected_plan_artifact(payload.site, payload.distribution_date, payload.calculator_document_id)
    accountant = excel.ACCOUNTANTS[payload.site]
    base = {
        "committed": False,
        "duplicate": False,
        "site": payload.site,
        "accountantCode": accountant,
        "distributionDate": payload.distribution_date.isoformat(),
        "calculatorDocumentId": payload.calculator_document_id,
        "planName": artifact["planName"],
        "planningSource": "CALCULATOR_DAILY_PLAN_SINGLE",
        "filename": artifact["filename"],
        "sheetName": "Belanja",
        "itemCount": len(artifact["items"]),
        "grandTotal": artifact["grandTotal"],
        "paguBgn": artifact["paguBgn"],
        "paguMinusEstimate": artifact["paguMinusEstimate"],
        "excelReady": True,
        "downloadAvailable": True,
        "downloadUrl": _selected_download_url(payload),
        "fileSizeBytes": len(artifact["xlsx"]),
        "driveUri": None,
        "driveUploadStatus": "NOT_REQUESTED" if not payload.commit else "PENDING",
        "driveUploadError": None,
        "retryable": False,
    }
    if not payload.commit:
        return base

    with connection() as conn:
        with conn.cursor() as cur:
            cycle_id = _ensure_cycle(cur, payload.site, payload.distribution_date)
            cur.execute(
                """
                select id,excel_evidence_uri,status,sent_at,generated_filename,drive_upload_status,drive_upload_error
                from accountant_submissions
                where upper(site)=upper(%s) and upper(accountant_code)=upper(%s)
                  and source_calculator_document_id=%s
                order by id desc limit 1
                """,
                (payload.site, accountant, payload.calculator_document_id),
            )
            existing = cur.fetchone()
            if existing and existing.get("excel_evidence_uri"):
                return {
                    **base,
                    "committed": True,
                    "duplicate": True,
                    "submissionId": existing["id"],
                    "driveUri": existing["excel_evidence_uri"],
                    "status": existing["status"],
                    "sentAt": existing["sent_at"],
                    "filename": existing.get("generated_filename") or artifact["filename"],
                    "driveUploadStatus": existing.get("drive_upload_status") or "UPLOADED",
                    "driveUploadError": existing.get("drive_upload_error"),
                }

            try:
                upload = upload_accountant_artifact(
                    kind="excel",
                    filename=artifact["filename"],
                    data=artifact["xlsx"],
                    mime_type=excel.XLSX_MIME,
                )
            except AccountantDriveUploadError as exc:
                error_text = str(exc)[:1500]
                cur.execute(
                    """
                    insert into accountant_submissions(
                      production_cycle_id,site,accountant_code,excel_evidence_uri,sent_at,status,
                      source_planning_snapshot_id,generated_filename,source_calculator_document_id,
                      source_plan_name,source_distribution_date,drive_upload_status,drive_upload_error,updated_at
                    ) values (%s,%s,%s,null,null,'EXCEL_READY_UPLOAD_FAILED',null,%s,%s,%s,%s,'FAILED',%s,now())
                    on conflict (site,accountant_code,source_calculator_document_id)
                    where source_calculator_document_id is not null
                    do update set generated_filename=excluded.generated_filename,
                      source_plan_name=excluded.source_plan_name,
                      source_distribution_date=excluded.source_distribution_date,
                      drive_upload_status='FAILED',drive_upload_error=excluded.drive_upload_error,
                      status=case when accountant_submissions.status='SENT' then accountant_submissions.status else 'EXCEL_READY_UPLOAD_FAILED' end,
                      updated_at=now()
                    returning id,status
                    """,
                    (cycle_id, payload.site, accountant, artifact["filename"], payload.calculator_document_id,
                     artifact["planName"], payload.distribution_date, error_text),
                )
                failed = cur.fetchone()
                conn.commit()
                return {
                    **base,
                    "committed": False,
                    "submissionId": failed["id"],
                    "status": failed["status"],
                    "driveUploadStatus": "FAILED",
                    "driveUploadError": error_text,
                    "retryable": True,
                }

            cur.execute(
                """
                insert into accountant_submissions(
                  production_cycle_id,site,accountant_code,excel_evidence_uri,sent_at,status,
                  source_planning_snapshot_id,generated_filename,source_calculator_document_id,
                  source_plan_name,source_distribution_date,drive_upload_status,drive_upload_error,updated_at
                ) values (%s,%s,%s,%s,null,'READY',null,%s,%s,%s,%s,'UPLOADED',null,now())
                on conflict (site,accountant_code,source_calculator_document_id)
                where source_calculator_document_id is not null
                do update set production_cycle_id=excluded.production_cycle_id,
                  excel_evidence_uri=excluded.excel_evidence_uri,generated_filename=excluded.generated_filename,
                  source_plan_name=excluded.source_plan_name,source_distribution_date=excluded.source_distribution_date,
                  drive_upload_status='UPLOADED',drive_upload_error=null,
                  status=case when accountant_submissions.status='SENT' then accountant_submissions.status else 'READY' end,
                  updated_at=now()
                returning id,status,sent_at
                """,
                (cycle_id, payload.site, accountant, upload["driveUri"], artifact["filename"],
                 payload.calculator_document_id, artifact["planName"], payload.distribution_date),
            )
            saved = cur.fetchone()
            conn.commit()
            return {
                **base,
                "committed": True,
                "submissionId": saved["id"],
                "driveUri": upload["driveUri"],
                "driveFolderId": upload["folderId"],
                "usedFallbackDriveFolder": upload["usedFallbackFolder"],
                "status": saved["status"],
                "sentAt": saved["sent_at"],
                "driveUploadStatus": "UPLOADED",
            }


@router.get("/accountant-excel/download-selected-plan")
def download_selected_plan_excel(
    site: Literal["MAJA", "CEMPLANG"],
    distribution_date: date = Query(alias="distributionDate"),
    calculator_document_id: str = Query(alias="calculatorDocumentId", min_length=1),
):
    require_db()
    artifact = _selected_plan_artifact(site, distribution_date, calculator_document_id)
    return StreamingResponse(
        io.BytesIO(artifact["xlsx"]),
        media_type=excel.XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact["filename"]}"',
            "Cache-Control": "no-store",
            "X-SPPG-Excel-Source": "calculator-daily-plan-single",
        },
    )


class AccountantInvoiceUploadIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1)
    invoice_number: str | None = Field(default=None, max_length=150)
    invoice_amount: float | None = Field(default=None, gt=0)
    received_at: datetime | None = None


def _invoice_bytes(payload: AccountantInvoiceUploadIn) -> bytes:
    mime = payload.mime_type.lower().strip()
    if mime not in ALLOWED_INVOICE_MIME:
        raise HTTPException(400, "invoice harus PDF/JPG/PNG/WEBP")
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "file invoice base64 tidak valid") from exc
    if not data:
        raise HTTPException(400, "file invoice kosong")
    if len(data) > MAX_INVOICE_BYTES:
        raise HTTPException(413, "file invoice maksimal 12 MB")
    return data


def _safe_filename(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return (name or "invoice")[:160]


@router.post("/accountant-submissions/{submission_id}/invoice-upload")
def upload_accountant_invoice(submission_id: int, payload: AccountantInvoiceUploadIn) -> dict[str, Any]:
    require_db()
    data = _invoice_bytes(payload)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id,site,accountant_code,status,source_plan_name,source_distribution_date
                from accountant_submissions where id=%s
                """,
                (submission_id,),
            )
            submission = cur.fetchone()
            if not submission:
                raise HTTPException(404, "accountant submission tidak ditemukan")
            if str(submission.get("status") or "").upper() != "SENT":
                raise HTTPException(409, "tandai Excel sebagai SENT dulu sebelum mencatat invoice balasan")

            cur.execute(
                """select id,invoice_number,invoice_amount,invoice_evidence_uri,received_at
                   from accountant_invoices where accountant_submission_id=%s order by id desc limit 1""",
                (submission_id,),
            )
            existing = cur.fetchone()
            if existing and existing.get("invoice_evidence_uri"):
                return {
                    "duplicate": True,
                    "accountantInvoiceId": existing["id"],
                    "invoiceNumber": existing.get("invoice_number"),
                    "invoiceAmount": existing.get("invoice_amount"),
                    "invoiceEvidenceUri": existing.get("invoice_evidence_uri"),
                    "receivedAt": existing.get("received_at"),
                }

            base_name = _safe_filename(payload.file_name)
            plan_slug = _slug(str(submission.get("source_plan_name") or submission["site"]))
            filename = f"invoice_{submission['site'].lower()}_{plan_slug}_{submission_id}_{base_name}"
            try:
                uploaded = upload_accountant_artifact(
                    kind="invoice",
                    filename=filename,
                    data=data,
                    mime_type=payload.mime_type.lower().strip(),
                )
            except AccountantDriveUploadError as exc:
                raise HTTPException(503, str(exc)[:1500]) from exc

            if existing:
                cur.execute(
                    """
                    update accountant_invoices set
                      invoice_number=coalesce(invoice_number,%s),
                      invoice_amount=coalesce(invoice_amount,%s),
                      invoice_evidence_uri=%s,
                      received_at=coalesce(received_at,%s,now())
                    where id=%s
                    returning id,invoice_number,invoice_amount,invoice_evidence_uri,received_at
                    """,
                    (payload.invoice_number, payload.invoice_amount, uploaded["driveUri"], payload.received_at, existing["id"]),
                )
            else:
                cur.execute(
                    """
                    insert into accountant_invoices(
                      accountant_submission_id,invoice_number,invoice_amount,invoice_evidence_uri,received_at
                    ) values (%s,%s,%s,%s,coalesce(%s,now()))
                    returning id,invoice_number,invoice_amount,invoice_evidence_uri,received_at
                    """,
                    (submission_id, payload.invoice_number, payload.invoice_amount, uploaded["driveUri"], payload.received_at),
                )
            invoice = cur.fetchone()
            conn.commit()
            return {
                "duplicate": False,
                "accountantInvoiceId": invoice["id"],
                "invoiceNumber": invoice.get("invoice_number"),
                "invoiceAmount": invoice.get("invoice_amount"),
                "invoiceEvidenceUri": invoice.get("invoice_evidence_uri"),
                "receivedAt": invoice.get("received_at"),
                "driveFolderId": uploaded["folderId"],
            }


@router.post("/accountant-invoices/{invoice_id}/create-maker")
def create_maker_from_accountant_invoice(invoice_id: int) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select i.id invoice_id,i.invoice_number,i.invoice_amount,
                       s.id submission_id,s.production_cycle_id,s.site
                from accountant_invoices i
                join accountant_submissions s on s.id=i.accountant_submission_id
                where i.id=%s
                """,
                (invoice_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "invoice akuntan tidak ditemukan")
            amount = float(row.get("invoice_amount") or 0)
            if amount <= 0:
                raise HTTPException(409, "nilai invoice belum tersedia")

            cur.execute("select id,status from bgn_makers where accountant_invoice_id=%s order by id desc limit 1", (invoice_id,))
            existing = cur.fetchone()
            if existing:
                return {"duplicate": True, "makerId": existing["id"], "status": existing["status"]}

            approver = APPROVERS.get(str(row["site"]).upper())
            if not approver:
                raise HTTPException(409, "approver site tidak tersedia")
            reference = row.get("invoice_number") or f"AKUNTAN-INV-{invoice_id}"
            cur.execute(
                """
                insert into bgn_makers(
                  production_cycle_id,site,reference_number,amount,status,accountant_invoice_id
                ) values (%s,%s,%s,%s,'CREATED',%s) returning id
                """,
                (row.get("production_cycle_id"), row["site"], reference, amount, invoice_id),
            )
            maker_id = int(cur.fetchone()["id"])
            cur.execute(
                """
                insert into bgn_approvals(
                  bgn_maker_id,approver_code,status,requested_at
                ) values (%s,%s,'PENDING',now()) returning id
                """,
                (maker_id, approver),
            )
            approval_id = int(cur.fetchone()["id"])
            conn.commit()
            return {
                "duplicate": False,
                "makerId": maker_id,
                "approvalId": approval_id,
                "approverCode": approver,
                "status": "CREATED",
                "approvalStatus": "PENDING",
            }
