from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.db import connection, database_ready

router = APIRouter(tags=["accountant-status"])
APPROVERS = {"MAJA": "EMBUN", "CEMPLANG": "MALIK"}


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
                   set sent_at=coalesce(sent_at,now()), status='SENT', updated_at=now()
                   where id=%s
                     and (excel_evidence_uri is not null or generated_filename is not null)
                   returning id,site,accountant_code,excel_evidence_uri,generated_filename,sent_at,status""",
                (submission_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "accountant submission tidak ditemukan atau Excel belum pernah dibuat")
            conn.commit()
            return {
                "submissionId": row["id"],
                "site": row["site"],
                "accountantCode": row["accountant_code"],
                "driveUri": row["excel_evidence_uri"],
                "filename": row["generated_filename"],
                "sentAt": row["sent_at"],
                "status": row["status"],
            }


@router.post("/bgn-makers/{maker_id}/approve-now")
def approve_bgn_maker_now(maker_id: int) -> dict[str, Any]:
    """Owner click-only approval. No proof file is required for this step."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id,site,status,reference_number,amount from bgn_makers where id=%s", (maker_id,))
            maker = cur.fetchone()
            if not maker:
                raise HTTPException(404, "maker BGN tidak ditemukan")

            cur.execute(
                """select id,approver_code,status,approved_at
                   from bgn_approvals where bgn_maker_id=%s
                   order by created_at desc,id desc limit 1""",
                (maker_id,),
            )
            approval = cur.fetchone()
            if approval:
                cur.execute(
                    """update bgn_approvals
                       set status='APPROVED',approved_at=coalesce(approved_at,now()),rejected_at=null
                       where id=%s
                       returning id,approver_code,status,approved_at""",
                    (approval["id"],),
                )
                approval = cur.fetchone()
            else:
                approver = APPROVERS.get(str(maker.get("site") or "").upper())
                if not approver:
                    raise HTTPException(409, "approver site tidak tersedia")
                cur.execute(
                    """insert into bgn_approvals(bgn_maker_id,approver_code,status,requested_at,approved_at)
                       values (%s,%s,'APPROVED',now(),now())
                       returning id,approver_code,status,approved_at""",
                    (maker_id, approver),
                )
                approval = cur.fetchone()

            cur.execute(
                """update bgn_makers
                   set status=case when upper(status)='PAID' then status else 'APPROVED' end
                   where id=%s returning status""",
                (maker_id,),
            )
            maker_status = cur.fetchone()["status"]
            conn.commit()

    return {
        "makerId": maker_id,
        "makerStatus": maker_status,
        "approvalId": approval["id"],
        "approverCode": approval["approver_code"],
        "approvalStatus": approval["status"],
        "approvedAt": approval["approved_at"],
        "evidenceRequired": False,
    }
