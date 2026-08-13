from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.db import connection, database_ready

router = APIRouter(tags=["accountant-status"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


@router.post("/accountant-submissions/{submission_id}/mark-sent")
def mark_accountant_submission_sent(submission_id: int) -> dict[str, Any]:
    """Explicit operator confirmation after the Excel was actually sent manually."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update accountant_submissions
                   set sent_at=coalesce(sent_at,now()), status='SENT'
                   where id=%s and excel_evidence_uri is not null
                   returning id,site,accountant_code,excel_evidence_uri,sent_at,status""",
                (submission_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "accountant submission tidak ditemukan atau Excel belum tersedia")
            conn.commit()
            return {
                "submissionId": row["id"],
                "site": row["site"],
                "accountantCode": row["accountant_code"],
                "driveUri": row["excel_evidence_uri"],
                "sentAt": row["sent_at"],
                "status": row["status"],
            }
