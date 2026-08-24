from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import accountant_selected_plan_api as selected
from backend import accountant_excel_api as excel
from backend.accountant_drive import AccountantDriveUploadError, upload_accountant_artifact
from backend.db import connection, database_ready
from backend.google_services import drive_service

router = APIRouter(tags=["accountant-correction"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _plan_hash(artifact: dict[str, Any]) -> str:
    payload = {
        "planName": artifact.get("planName"),
        "items": [
            {
                "item_name": row.get("item_name"),
                "planned_qty": row.get("planned_qty"),
                "unit": row.get("unit"),
                "planning_price": row.get("planning_price"),
                "preferred_vendor_code": row.get("preferred_vendor_code"),
                "category_code": row.get("category_code"),
                "notes": row.get("notes"),
            }
            for row in artifact.get("items") or []
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _drive_file_id(uri: str | None) -> str | None:
    value = str(uri or "")
    for pattern in (r"/d/([A-Za-z0-9_-]+)", r"[?&]id=([A-Za-z0-9_-]+)"):
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return None


def _delete_drive_uri(uri: str | None) -> dict[str, Any]:
    file_id = _drive_file_id(uri)
    if not file_id:
        return {"attempted": False, "deleted": False, "reason": "file_id_not_found"}
    try:
        drive_service().files().delete(fileId=file_id, supportsAllDrives=True).execute()
        return {"attempted": True, "deleted": True, "fileId": file_id}
    except Exception as exc:
        return {"attempted": True, "deleted": False, "fileId": file_id, "error": str(exc)[:700]}


def _safe_filename(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    name = str(value).replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    if not name:
        return fallback
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    return name[:180]


class FreshSelectedPlanExcelIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    distribution_date: date
    calculator_document_id: str = Field(min_length=1)
    custom_filename: str | None = Field(default=None, max_length=180)
    commit: bool = False


@router.post("/accountant-excel/from-selected-plan-fresh")
def fresh_selected_plan_excel(payload: FreshSelectedPlanExcelIn) -> dict[str, Any]:
    """Always rebuild from the current Calculator document instead of returning an old Drive artifact."""
    require_db()
    artifact = selected._selected_plan_artifact(payload.site, payload.distribution_date, payload.calculator_document_id)
    artifact["filename"] = _safe_filename(payload.custom_filename, artifact["filename"])
    source_hash = _plan_hash(artifact)
    candidate = artifact["candidate"]
    source_updated_at = candidate.get("updated_at")
    accountant = excel.ACCOUNTANTS[payload.site]
    download_payload = selected.SelectedPlanExcelIn(
        site=payload.site,
        distribution_date=payload.distribution_date,
        calculator_document_id=payload.calculator_document_id,
        commit=False,
    )

    existing = None
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select s.id,s.excel_evidence_uri,s.status,s.sent_at,s.generated_filename,
                       s.drive_upload_status,s.drive_upload_error,s.source_plan_hash,s.source_plan_updated_at,
                       exists(select 1 from accountant_invoices i where i.accountant_submission_id=s.id) as has_invoice
                from accountant_submissions s
                where upper(s.site)=upper(%s) and upper(s.accountant_code)=upper(%s)
                  and s.source_calculator_document_id=%s
                order by s.id desc limit 1
                """,
                (payload.site, accountant, payload.calculator_document_id),
            )
            existing = cur.fetchone()

    source_changed = bool(existing and existing.get("source_plan_hash") and existing.get("source_plan_hash") != source_hash)
    base = {
        "committed": False,
        "duplicate": False,
        "site": payload.site,
        "accountantCode": accountant,
        "distributionDate": payload.distribution_date.isoformat(),
        "calculatorDocumentId": payload.calculator_document_id,
        "planName": artifact["planName"],
        "planningSource": "CALCULATOR_DAILY_PLAN_SINGLE_FRESH",
        "filename": artifact["filename"],
        "sheetName": "Belanja",
        "itemCount": len(artifact["items"]),
        "grandTotal": artifact["grandTotal"],
        "paguBgn": artifact["paguBgn"],
        "paguMinusEstimate": artifact["paguMinusEstimate"],
        "excelReady": True,
        "downloadAvailable": True,
        "downloadUrl": selected._selected_download_url(download_payload),
        "fileSizeBytes": len(artifact["xlsx"]),
        "sourcePlanHash": source_hash,
        "sourceUpdatedAt": selected._json_safe(source_updated_at),
        "sourceChangedSinceLastExcel": source_changed,
        "existingSubmissionId": existing.get("id") if existing else None,
        "existingSubmissionStatus": existing.get("status") if existing else None,
        "driveUri": existing.get("excel_evidence_uri") if existing and not source_changed else None,
        "driveUploadStatus": "NOT_REQUESTED" if not payload.commit else "PENDING",
        "driveUploadError": None,
        "retryable": False,
    }
    if not payload.commit:
        return base

    if existing and str(existing.get("status") or "").upper() == "SENT":
        raise HTTPException(
            409,
            detail={
                "message": "Perencanaan ini sudah memiliki Excel berstatus SENT. Jika datanya salah, gunakan Hapus Alur untuk menghapus Excel → Invoice → Maker yang salah, lalu buat ulang dari perencanaan terbaru.",
                "submissionId": existing["id"],
                "sourceChanged": source_changed,
            },
        )

    try:
        uploaded = upload_accountant_artifact(
            kind="excel",
            filename=artifact["filename"],
            data=artifact["xlsx"],
            mime_type=excel.XLSX_MIME,
        )
    except AccountantDriveUploadError as exc:
        raise HTTPException(503, str(exc)[:1500]) from exc

    old_drive = existing.get("excel_evidence_uri") if existing else None
    with connection() as conn:
        with conn.cursor() as cur:
            cycle_id = selected._ensure_cycle(cur, payload.site, payload.distribution_date)
            cur.execute(
                """
                insert into accountant_submissions(
                  production_cycle_id,site,accountant_code,excel_evidence_uri,sent_at,status,
                  source_planning_snapshot_id,generated_filename,source_calculator_document_id,
                  source_plan_name,source_distribution_date,drive_upload_status,drive_upload_error,updated_at,
                  source_plan_hash,source_plan_updated_at
                ) values (%s,%s,%s,%s,null,'READY',null,%s,%s,%s,%s,'UPLOADED',null,now(),%s,%s)
                on conflict (site,accountant_code,source_calculator_document_id)
                where source_calculator_document_id is not null
                do update set production_cycle_id=excluded.production_cycle_id,
                  excel_evidence_uri=excluded.excel_evidence_uri,
                  generated_filename=excluded.generated_filename,
                  source_plan_name=excluded.source_plan_name,
                  source_distribution_date=excluded.source_distribution_date,
                  drive_upload_status='UPLOADED',drive_upload_error=null,
                  status='READY',sent_at=null,
                  source_plan_hash=excluded.source_plan_hash,
                  source_plan_updated_at=excluded.source_plan_updated_at,
                  updated_at=now()
                returning id,status,sent_at
                """,
                (
                    cycle_id,payload.site,accountant,uploaded["driveUri"],artifact["filename"],
                    payload.calculator_document_id,artifact["planName"],payload.distribution_date,
                    source_hash,source_updated_at,
                ),
            )
            saved = cur.fetchone()
            conn.commit()

    drive_cleanup = None
    if old_drive and old_drive != uploaded["driveUri"]:
        drive_cleanup = _delete_drive_uri(old_drive)
    return {
        **base,
        "committed": True,
        "submissionId": saved["id"],
        "status": saved["status"],
        "sentAt": saved["sent_at"],
        "driveUri": uploaded["driveUri"],
        "driveFolderId": uploaded["folderId"],
        "driveUploadStatus": "UPLOADED",
        "sourceChangedSinceLastExcel": False,
        "replacedPreviousExcel": bool(old_drive),
        "previousDriveCleanup": drive_cleanup,
    }


@router.delete("/accountant-submissions/{submission_id}/cascade")
def delete_accountant_submission_cascade(submission_id: int) -> dict[str, Any]:
    """Delete an erroneous Excel→Invoice→Maker chain before funds/approval are finalized."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from accountant_submissions where id=%s", (submission_id,))
            submission = cur.fetchone()
            if not submission:
                raise HTTPException(404, "submission akuntan tidak ditemukan")

            cur.execute("select id,invoice_evidence_uri from accountant_invoices where accountant_submission_id=%s", (submission_id,))
            invoices = [dict(row) for row in cur.fetchall()]
            invoice_ids = [int(row["id"]) for row in invoices]
            maker_ids: list[int] = []
            if invoice_ids:
                cur.execute("select id from bgn_makers where accountant_invoice_id = any(%s)", (invoice_ids,))
                maker_ids = [int(row["id"]) for row in cur.fetchall()]

            if maker_ids:
                cur.execute(
                    "select count(*) n from bgn_approvals where bgn_maker_id=any(%s) and upper(status)='APPROVED'",
                    (maker_ids,),
                )
                if int(cur.fetchone()["n"] or 0) > 0:
                    raise HTTPException(409, "Tidak boleh menghapus alur yang approval BGN-nya sudah APPROVED. Lakukan koreksi akuntansi, bukan delete.")
                cur.execute("select count(*) n from bgn_receipts where bgn_maker_id=any(%s)", (maker_ids,))
                if int(cur.fetchone()["n"] or 0) > 0:
                    raise HTTPException(409, "Tidak boleh menghapus alur yang sudah memiliki penerimaan dana BGN.")

            if maker_ids:
                cur.execute("delete from bgn_approvals where bgn_maker_id=any(%s)", (maker_ids,))
                cur.execute("delete from bgn_makers where id=any(%s)", (maker_ids,))
            if invoice_ids:
                cur.execute("delete from accountant_invoices where id=any(%s)", (invoice_ids,))
            cur.execute("delete from accountant_submissions where id=%s", (submission_id,))
            conn.commit()

    drive_results = []
    for uri in [submission.get("excel_evidence_uri"), *[row.get("invoice_evidence_uri") for row in invoices]]:
        if uri:
            drive_results.append(_delete_drive_uri(uri))
    return {
        "deleted": True,
        "submissionId": submission_id,
        "deletedInvoiceIds": invoice_ids,
        "deletedMakerIds": maker_ids,
        "driveCleanup": drive_results,
        "note": "Production cycle, Calculator planning, PO, receiving, finance ledger, dan stok tidak dihapus.",
    }
