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
                       set status='APPROVED',approved_at=coalesce(approved_at,now()),rejected_at=null,
                           approval_method=coalesce(approval_method,'MANUAL_CLICK')
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
                    """insert into bgn_approvals(bgn_maker_id,approver_code,status,requested_at,approved_at,approval_method)
                       values (%s,%s,'APPROVED',now(),now(),'MANUAL_CLICK')
                       returning id,approver_code,status,approved_at""",
                    (maker_id, approver),
                )
                approval = cur.fetchone()

            cur.execute(
                """update bgn_makers
                   set status='PAID'
                   where id=%s returning status""",
                (maker_id,),
            )
            maker_status = cur.fetchone()["status"]
            cur.execute("select id,received_at,evidence_uri from bgn_receipts where bgn_maker_id=%s order by created_at desc,id desc limit 1", (maker_id,))
            receipt = cur.fetchone()
            if not receipt:
                cur.execute(
                    """insert into bgn_receipts(bgn_maker_id,destination_account_type,amount,received_at,evidence_uri)
                       values (%s,'SPPG',%s,coalesce(%s,now()),null)
                       returning id,received_at,evidence_uri""",
                    (maker_id, maker["amount"], approval["approved_at"]),
                )
                receipt = cur.fetchone()
            conn.commit()

    return {
        "makerId": maker_id,
        "makerStatus": maker_status,
        "approvalId": approval["id"],
        "approverCode": approval["approver_code"],
        "approvalStatus": approval["status"],
        "approvedAt": approval["approved_at"],
        "receiptId": receipt["id"],
        "paidAt": receipt["received_at"],
        "evidenceRequired": False,
    }


@router.post("/bgn-makers/{maker_id}/cancel-approval")
def cancel_bgn_maker_approval(maker_id: int) -> dict[str, Any]:
    """Undo an accidental approval as long as the maker has not been paid/received."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select m.id,m.site,m.status,m.reference_number,m.amount,
                          exists(select 1 from bgn_receipts r where r.bgn_maker_id=m.id) as has_receipt
                   from bgn_makers m where m.id=%s""",
                (maker_id,),
            )
            maker = cur.fetchone()
            if not maker:
                raise HTTPException(404, "maker BGN tidak ditemukan")
            if bool(maker.get("has_receipt")) or str(maker.get("status") or "").upper() == "PAID":
                raise HTTPException(409, "approval tidak dapat dibatalkan karena Maker sudah PAID / memiliki penerimaan dana")

            cur.execute(
                """select id,approver_code,status,approved_at
                   from bgn_approvals where bgn_maker_id=%s
                   order by created_at desc,id desc limit 1""",
                (maker_id,),
            )
            approval = cur.fetchone()
            if not approval:
                raise HTTPException(409, "maker belum memiliki approval")

            cur.execute(
                """update bgn_approvals
                   set status='PENDING',approved_at=null,rejected_at=null
                   where id=%s
                   returning id,approver_code,status,approved_at""",
                (approval["id"],),
            )
            approval = cur.fetchone()
            cur.execute(
                """update bgn_makers
                   set status=case when upper(status)='PAID' then status else 'CREATED' end
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
        "cancelled": True,
    }


@router.post("/bgn-makers/{maker_id}/cancel-maker")
def cancel_bgn_maker(maker_id: int) -> dict[str, Any]:
    """Remove an accidental Maker while its approval is still pending.

    The source invoice and Excel submission remain intact, so the operator can
    correct the document and create a new Maker. Paid or approved Makers are
    intentionally protected from deletion.
    """
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select m.id,m.accountant_invoice_id,m.status,
                          exists(select 1 from bgn_receipts r where r.bgn_maker_id=m.id) as has_receipt,
                          coalesce((select upper(a.status) from bgn_approvals a
                                    where a.bgn_maker_id=m.id
                                    order by a.created_at desc,a.id desc limit 1),'PENDING') as approval_status
                   from bgn_makers m where m.id=%s""",
                (maker_id,),
            )
            maker = cur.fetchone()
            if not maker:
                raise HTTPException(404, "maker BGN tidak ditemukan")
            if bool(maker.get("has_receipt")) or str(maker.get("status") or "").upper() == "PAID":
                raise HTTPException(409, "Maker tidak dapat dibatalkan karena sudah PAID / memiliki penerimaan dana")
            if str(maker.get("approval_status") or "").upper() == "APPROVED":
                raise HTTPException(409, "Maker sudah APPROVED. Batalkan approval terlebih dahulu sebelum membatalkan Maker.")

            cur.execute("delete from bgn_approvals where bgn_maker_id=%s", (maker_id,))
            cur.execute("delete from bgn_makers where id=%s", (maker_id,))
            conn.commit()

    return {
        "makerId": maker_id,
        "accountantInvoiceId": maker.get("accountant_invoice_id"),
        "cancelled": True,
        "note": "Maker dan approval pending dihapus. Invoice serta Excel Akuntan tetap tersimpan.",
    }
