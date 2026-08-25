from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.accountant_drive import AccountantDriveUploadError, upload_accountant_artifact
from backend.db import connection, database_ready

router = APIRouter(tags=["bgn-paid"])
MAX_EVIDENCE_BYTES = 12 * 1024 * 1024
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


class BgnApproveIn(BaseModel):
    commit: bool = False
    approved_at: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="operator", max_length=100)


class BgnPaidIn(BaseModel):
    commit: bool = False
    paid_at: datetime | None = None
    evidence_uri: str | None = Field(default=None, max_length=2000)
    file_name: str | None = Field(default=None, max_length=180)
    mime_type: str | None = Field(default=None, max_length=120)
    content_base64: str | None = None
    note: str | None = Field(default=None, max_length=1000)
    actor: str = Field(default="operator", max_length=100)


def _safe_filename(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return (name or "bukti_paid")[:160]


def _decode_file(payload: BgnPaidIn) -> tuple[bytes, str, str] | None:
    if not payload.content_base64:
        return None
    mime = str(payload.mime_type or "").lower().strip()
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, "bukti paid harus PDF/JPG/PNG/WEBP")
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "file bukti paid base64 tidak valid") from exc
    if not data:
        raise HTTPException(400, "file bukti paid kosong")
    if len(data) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, "file bukti paid maksimal 12 MB")
    return data, mime, _safe_filename(payload.file_name or "bukti_paid")


def _maker_state(cur: Any, maker_id: int) -> dict[str, Any]:
    cur.execute(
        """
        select m.id,m.site,m.reference_number,m.amount,m.status,m.accountant_invoice_id,
               a.id as approval_id,a.approver_code,a.status as approval_status,a.approved_at,
               r.id as receipt_id,r.amount as receipt_amount,r.received_at,r.evidence_uri
        from bgn_makers m
        left join lateral (
          select * from bgn_approvals x where x.bgn_maker_id=m.id order by x.created_at desc,x.id desc limit 1
        ) a on true
        left join lateral (
          select * from bgn_receipts x where x.bgn_maker_id=m.id order by x.created_at desc,x.id desc limit 1
        ) r on true
        where m.id=%s
        """,
        (maker_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "maker BGN tidak ditemukan")
    return dict(row)


@router.post("/bgn-makers/{maker_id}/confirm-approved")
def confirm_bgn_approved(maker_id: int, payload: BgnApproveIn) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn:
        with conn.cursor() as cur:
            row = _maker_state(cur, maker_id)
            preview = {
                "committed": False,
                "makerId": maker_id,
                "site": row.get("site"),
                "referenceNumber": row.get("reference_number"),
                "amount": row.get("amount"),
                "currentApprovalStatus": row.get("approval_status"),
                "alreadyApproved": str(row.get("approval_status") or "").upper() == "APPROVED",
            }
            if not payload.commit:
                return preview
            if not row.get("approval_id"):
                raise HTTPException(409, "maker belum memiliki approval")
            cur.execute(
                """
                update bgn_approvals
                set status='APPROVED',approved_at=coalesce(approved_at,%s,now()),rejected_at=null
                where id=%s
                returning id,status,approved_at
                """,
                (payload.approved_at, row["approval_id"]),
            )
            approval = cur.fetchone()
            cur.execute(
                "update bgn_makers set status='PAID' where id=%s",
                (maker_id,),
            )
            if row.get("receipt_id"):
                cur.execute(
                    """update bgn_receipts set amount=%s,received_at=coalesce(received_at,%s,now()),
                           destination_account_type=coalesce(destination_account_type,'SPPG') where id=%s
                       returning id,received_at,evidence_uri""",
                    (row.get("amount"), payload.approved_at, row["receipt_id"]),
                )
            else:
                cur.execute(
                    """insert into bgn_receipts(bgn_maker_id,destination_account_type,amount,received_at,evidence_uri)
                       values (%s,'SPPG',%s,coalesce(%s,now()),null)
                       returning id,received_at,evidence_uri""",
                    (maker_id, row.get("amount"), payload.approved_at),
                )
            receipt = cur.fetchone()
            conn.commit()
    return {
        **preview,
        "committed": True,
        "approvalId": approval["id"],
        "approvalStatus": approval["status"],
        "approvedAt": approval["approved_at"],
        "makerStatus": "PAID",
        "receiptId": receipt["id"],
        "paidAt": receipt["received_at"],
        "actor": payload.actor,
        "note": payload.note,
    }


@router.post("/bgn-makers/{maker_id}/confirm-paid")
def confirm_bgn_paid(maker_id: int, payload: BgnPaidIn) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "database unavailable")

    evidence_upload = _decode_file(payload)
    with connection() as conn:
        with conn.cursor() as cur:
            row = _maker_state(cur, maker_id)

    preview = {
        "committed": False,
        "makerId": maker_id,
        "site": row.get("site"),
        "referenceNumber": row.get("reference_number"),
        "amount": row.get("amount"),
        "currentMakerStatus": row.get("status"),
        "currentApprovalStatus": row.get("approval_status"),
        "alreadyPaid": bool(row.get("receipt_id") or str(row.get("status") or "").upper() == "PAID"),
        "hasExistingEvidence": bool(row.get("evidence_uri")),
        "willUploadEvidence": bool(evidence_upload),
        "willUseEvidenceUri": bool(payload.evidence_uri),
    }
    if not payload.commit:
        return preview

    evidence_uri = (payload.evidence_uri or "").strip() or row.get("evidence_uri")
    if evidence_upload:
        data, mime, original_name = evidence_upload
        filename = f"bukti_paid_bgn_{str(row.get('site') or '').lower()}_{maker_id}_{original_name}"
        try:
            uploaded = upload_accountant_artifact(
                kind="paid", filename=filename, data=data, mime_type=mime,
                site=str(row.get("site") or ""), bucket="BUKTI_PAID",
            )
        except AccountantDriveUploadError as exc:
            raise HTTPException(503, str(exc)[:1500]) from exc
        evidence_uri = uploaded["driveUri"]

    paid_at = payload.paid_at
    with connection() as conn:
        with conn.cursor() as cur:
            current = _maker_state(cur, maker_id)
            if current.get("approval_id"):
                cur.execute(
                    """
                    update bgn_approvals
                    set status='APPROVED',approved_at=coalesce(approved_at,%s,now()),rejected_at=null
                    where id=%s
                    """,
                    (paid_at, current["approval_id"]),
                )
            else:
                raise HTTPException(409, "maker belum memiliki approval")

            cur.execute("update bgn_makers set status='PAID' where id=%s", (maker_id,))

            if current.get("receipt_id"):
                cur.execute(
                    """
                    update bgn_receipts
                    set amount=%s,received_at=coalesce(received_at,%s,now()),
                        evidence_uri=coalesce(%s,evidence_uri),destination_account_type=coalesce(destination_account_type,'SPPG')
                    where id=%s
                    returning id,amount,received_at,evidence_uri
                    """,
                    (current.get("amount"), paid_at, evidence_uri, current["receipt_id"]),
                )
            else:
                cur.execute(
                    """
                    insert into bgn_receipts(bgn_maker_id,destination_account_type,amount,received_at,evidence_uri)
                    values (%s,'SPPG',%s,coalesce(%s,now()),%s)
                    returning id,amount,received_at,evidence_uri
                    """,
                    (maker_id, current.get("amount"), paid_at, evidence_uri),
                )
            receipt = cur.fetchone()
            conn.commit()

    return {
        **preview,
        "committed": True,
        "makerStatus": "PAID",
        "approvalStatus": "APPROVED",
        "receiptId": receipt["id"],
        "receivedAt": receipt.get("received_at"),
        "evidenceUri": receipt.get("evidence_uri"),
        "actor": payload.actor,
        "note": payload.note,
    }
