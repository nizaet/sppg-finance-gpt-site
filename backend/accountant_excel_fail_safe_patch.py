from __future__ import annotations

import io
import os
from datetime import date
from typing import Any
from urllib.parse import urlencode

from fastapi import Query
from fastapi.responses import StreamingResponse

from backend import accountant_excel_api as excel

_INSTALLED = False


def _download_url(payload: excel.AccountantExcelFromPlanningIn) -> str:
    params: dict[str, Any] = {"site": payload.site, "distribution_date": payload.distribution_date.isoformat()}
    if payload.planning_snapshot_id is not None:
        params["planning_snapshot_id"] = payload.planning_snapshot_id
    return "/v1/accountant-excel/download?" + urlencode(params)


def _base_result(payload: excel.AccountantExcelFromPlanningIn, snapshot: dict[str, Any], items: list[dict[str, Any]],
                 rows: list[list[Any]], grand_total: float, pagu: float | None, delta: float | None,
                 filename: str) -> dict[str, Any]:
    return {
        "committed": False,
        "duplicate": False,
        "site": payload.site,
        "accountantCode": excel.ACCOUNTANTS[payload.site],
        "planningSnapshotId": snapshot["id"],
        "productionCycleId": snapshot.get("production_cycle_id"),
        "distributionDate": payload.distribution_date.isoformat(),
        "filename": filename,
        "sheetName": "Belanja",
        "columns": rows[0],
        "itemCount": len(items),
        "grandTotal": grand_total,
        "paguBgn": pagu,
        "paguMinusEstimate": delta,
        "driveUri": None,
        "excelReady": True,
        "downloadAvailable": True,
        "downloadUrl": _download_url(payload),
        "driveUploadStatus": "NOT_REQUESTED" if not payload.commit else "PENDING",
        "driveUploadError": None,
        "retryable": False,
        "failSafeVersion": "accountant-excel-v2",
    }


def accountant_excel_from_planning_fail_safe(payload: excel.AccountantExcelFromPlanningIn) -> dict[str, Any]:
    """Build XLSX independently from Drive availability; Drive is a delivery channel, not the artifact itself."""
    excel.require_db()
    accountant = excel.ACCOUNTANTS[payload.site]
    with excel.connection() as conn:
        with conn.cursor() as cur:
            snapshot, items = excel._load_snapshot(cur, payload)
            rows, grand_total, pagu, delta = excel._build_rows(snapshot, items)
            filename = f"daftar_belanja_{payload.distribution_date.isoformat()}_{payload.site.lower()}.xlsx"
            xlsx = excel._workbook_bytes(rows)
            result = _base_result(payload, snapshot, items, rows, grand_total, pagu, delta, filename)
            result["fileSizeBytes"] = len(xlsx)
            if not payload.commit:
                return result

            cur.execute(
                """select id,excel_evidence_uri,status,sent_at,generated_filename
                   from accountant_submissions
                   where upper(site)=upper(%s) and upper(accountant_code)=upper(%s)
                     and source_planning_snapshot_id=%s""",
                (payload.site, accountant, snapshot["id"]),
            )
            existing = cur.fetchone()
            if existing:
                result.update({
                    "committed": True,
                    "duplicate": True,
                    "submissionId": existing["id"],
                    "driveUri": existing["excel_evidence_uri"],
                    "status": existing["status"],
                    "sentAt": existing["sent_at"],
                    "filename": existing["generated_filename"] or filename,
                    "driveUploadStatus": "UPLOADED" if existing["excel_evidence_uri"] else "UNKNOWN",
                })
                return result

            folder_id = os.getenv("SPPG_DRIVE_ACCOUNTANT_FOLDER_ID", "").strip()
            try:
                drive_uri = excel.upload_bytes_to_drive(folder_id, filename, xlsx, excel.XLSX_MIME)
            except Exception as exc:
                # SELECTs above created no domain changes. Roll back the read transaction
                # and return a valid downloadable workbook result instead of raw 500/503.
                conn.rollback()
                result.update({
                    "committed": False,
                    "status": "EXCEL_READY_UPLOAD_FAILED",
                    "driveUploadStatus": "FAILED",
                    "driveUploadError": f"{type(exc).__name__}: {exc}"[:1500],
                    "retryable": True,
                })
                return result

            cur.execute(
                """insert into accountant_submissions(
                     production_cycle_id,site,accountant_code,excel_evidence_uri,sent_at,status,
                     source_planning_snapshot_id,generated_filename
                   ) values (%s,%s,%s,%s,null,'READY',%s,%s) returning id""",
                (snapshot.get("production_cycle_id"), payload.site, accountant, drive_uri, snapshot["id"], filename),
            )
            submission_id = cur.fetchone()["id"]
            conn.commit()
            result.update({
                "committed": True,
                "submissionId": submission_id,
                "driveUri": drive_uri,
                "status": "READY",
                "sentAt": None,
                "driveUploadStatus": "UPLOADED",
            })
            return result


def download_accountant_excel(
    site: str = Query(..., pattern="^(MAJA|CEMPLANG)$"),
    distribution_date: date = Query(...),
    planning_snapshot_id: int | None = Query(default=None, ge=1),
):
    """Regenerate the same workbook directly from the planning snapshot without contacting Drive."""
    excel.require_db()
    payload = excel.AccountantExcelFromPlanningIn(
        site=site,
        distribution_date=distribution_date,
        planning_snapshot_id=planning_snapshot_id,
        commit=False,
    )
    with excel.connection() as conn:
        with conn.cursor() as cur:
            snapshot, items = excel._load_snapshot(cur, payload)
            rows, _, _, _ = excel._build_rows(snapshot, items)
            xlsx = excel._workbook_bytes(rows)
    filename = f"daftar_belanja_{distribution_date.isoformat()}_{site.lower()}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type=excel.XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-SPPG-Excel-Source": "planning-snapshot",
        },
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    excel.accountant_excel_from_planning = accountant_excel_from_planning_fail_safe
    found = False
    for route in excel.router.routes:
        if getattr(route, "path", "") == "/accountant-excel/from-planning" and "POST" in (getattr(route, "methods", set()) or set()):
            route.endpoint = accountant_excel_from_planning_fail_safe
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = accountant_excel_from_planning_fail_safe
            found = True
            break
    if not found:
        raise RuntimeError("accountant Excel route not found; refusing unsafe patch install")
    if not any(getattr(route, "path", "") == "/accountant-excel/download" for route in excel.router.routes):
        excel.router.add_api_route(
            "/accountant-excel/download",
            download_accountant_excel,
            methods=["GET"],
            include_in_schema=False,
            summary="Download generated Accountant Excel directly",
        )
    _INSTALLED = True
