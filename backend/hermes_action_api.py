from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.db import connection, database_ready
from backend.gpt_bridge_api import require_gpt_auth


router = APIRouter(prefix="/gpt/hermes-actions", tags=["hermes-actions"])
owner_router = APIRouter(prefix="/hermes-actions", tags=["hermes-action-approvals"])
approval_bearer = HTTPBearer(auto_error=False)

Site = Literal["MAJA", "CEMPLANG"]
ActionType = Literal[
    "CREATE_PO",
    "RECORD_RECEIVING",
    "RECORD_VENDOR_PAYABLE",
    "RECORD_VENDOR_PAYMENT",
    "RECORD_FINANCE_TRANSACTION",
    "SEND_WHATSAPP",
]


class HermesActionProposalIn(BaseModel):
    source_ref: str = Field(min_length=1, max_length=300)
    action_type: ActionType
    site: Site
    vendor_code: str | None = Field(default=None, max_length=100)
    entity_code: str | None = Field(default=None, max_length=160)
    target_type: str = Field(min_length=1, max_length=100)
    target_id: str | None = Field(default=None, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class HermesActionDecisionIn(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    actor: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=2000)

    @field_validator("actor")
    @classmethod
    def actor_must_be_human_approver(cls, value: str) -> str:
        actor = value.strip()
        if actor.lower() in {"hermes", "hermes-agent", "sppg-hermes-gateway"}:
            raise ValueError("Hermes cannot approve its own proposal")
        return actor


class OwnerHermesActionDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT"]
    note: str = Field(default="", max_length=2000)


def require_hermes_approval_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(approval_bearer),
) -> None:
    expected = os.getenv("SPPG_HERMES_APPROVAL_KEY", "").strip()
    if not expected:
        raise HTTPException(503, "SPPG_HERMES_APPROVAL_KEY is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Approval bearer token required")
    if not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(403, "Invalid approval key")


def require_owner_request(request: Request) -> None:
    if str(getattr(request.state, "sppg_role", "")).upper() != "OWNER":
        raise HTTPException(403, "OWNER access required")


def proposal_keys(payload: HermesActionProposalIn) -> tuple[str, str]:
    canonical = json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"hermes-proposal:{digest}", f"hermes-action:{digest}"


def _require_database() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


@router.get("/status", dependencies=[Depends(require_gpt_auth)])
def hermes_action_status() -> dict[str, Any]:
    return {
        "databaseReady": database_ready(),
        "proposalWritesExposed": True,
        "approvalConfigured": bool(os.getenv("SPPG_HERMES_APPROVAL_KEY", "").strip()),
        "executionExposed": False,
        "mode": "PROPOSE_AND_APPROVE_ONLY",
    }


@router.post("/proposals", dependencies=[Depends(require_gpt_auth)])
def create_hermes_action_proposal(payload: HermesActionProposalIn) -> dict[str, Any]:
    """Stage a Hermes proposal without mutating operational records."""
    _require_database()
    event_key, idempotency_key = proposal_keys(payload)
    candidate_payload = {
        "sourceRef": payload.source_ref,
        "rationale": payload.rationale,
        "proposedAction": {
            "actionType": payload.action_type,
            "targetType": payload.target_type,
            "targetId": payload.target_id,
            "payload": payload.payload,
        },
        "createdBy": "hermes",
        "executionAuthorized": False,
    }
    action_payload = {
        "site": payload.site,
        "vendorCode": payload.vendor_code,
        "entityCode": payload.entity_code,
        "rationale": payload.rationale,
        "payload": payload.payload,
        "executionAuthorized": False,
    }

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into ingest_sources(source_type, external_id, source_hash)
                   values ('HERMES', %s, %s)
                   on conflict (source_type, external_id)
                   do update set source_hash=excluded.source_hash
                   returning id""",
                (payload.source_ref, event_key),
            )
            source_id = cur.fetchone()["id"]
            cur.execute(
                """insert into candidate_events(
                     event_key,source_id,event_type,site,vendor_code,entity_code,event_time,
                     confidence,requires_confirmation,payload,raw_text,parser_version,status
                   ) values (%s,%s,%s,%s,%s,%s,now(),%s,true,%s::jsonb,%s,
                             'hermes-action-proposal-v1','PENDING')
                   on conflict (event_key) do nothing
                   returning id,status,created_at""",
                (
                    event_key,
                    source_id,
                    f"HERMES_PROPOSAL_{payload.action_type}",
                    payload.site,
                    payload.vendor_code,
                    payload.entity_code,
                    payload.confidence,
                    json.dumps(candidate_payload, ensure_ascii=False),
                    payload.rationale,
                ),
            )
            candidate = cur.fetchone()
            inserted = candidate is not None
            if candidate is None:
                cur.execute(
                    "select id,status,created_at from candidate_events where event_key=%s",
                    (event_key,),
                )
                candidate = cur.fetchone()
            if candidate is None:
                raise HTTPException(500, "proposal was not persisted")

            cur.execute(
                """insert into workflow_actions(
                     candidate_event_id,action_type,target_type,target_id,action_payload,status,idempotency_key
                   ) values (%s,%s,%s,%s,%s::jsonb,'PLANNED',%s)
                   on conflict (idempotency_key) do nothing
                   returning id,status,created_at""",
                (
                    candidate["id"],
                    payload.action_type,
                    payload.target_type,
                    payload.target_id,
                    json.dumps(action_payload, ensure_ascii=False),
                    idempotency_key,
                ),
            )
            action = cur.fetchone()
            if action is None:
                cur.execute(
                    "select id,status,created_at from workflow_actions where idempotency_key=%s",
                    (idempotency_key,),
                )
                action = cur.fetchone()
            if action is None:
                raise HTTPException(500, "workflow action was not persisted")

            cur.execute(
                """insert into event_audit_log(
                     candidate_event_id,workflow_action_id,action,actor,details
                   ) values (%s,%s,%s,'hermes',%s::jsonb)""",
                (
                    candidate["id"],
                    action["id"],
                    "HERMES_PROPOSAL_CREATED" if inserted else "HERMES_PROPOSAL_REPLAYED",
                    json.dumps(
                        {
                            "sourceRef": payload.source_ref,
                            "actionType": payload.action_type,
                            "executionAuthorized": False,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        conn.commit()

    return {
        "proposalId": candidate["id"],
        "actionId": action["id"],
        "candidateStatus": candidate["status"],
        "actionStatus": action["status"],
        "inserted": inserted,
        "approvalRequired": True,
        "executed": False,
        "executionLocked": True,
    }


@router.get("/proposals", dependencies=[Depends(require_gpt_auth)])
def list_hermes_action_proposals(
    site: Site | None = None,
    status: Literal["PENDING", "VALIDATED", "REJECTED", "APPLIED", "SUPERSEDED"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    _require_database()
    sql = """select ce.id as proposal_id,wa.id as action_id,ce.event_key,ce.event_type,
                    ce.site,ce.vendor_code,ce.entity_code,ce.confidence,ce.status as candidate_status,
                    ce.payload,ce.raw_text,ce.created_at,ce.validated_at,ce.validated_by,
                    ce.rejection_reason,wa.action_type,wa.target_type,wa.target_id,
                    wa.action_payload,wa.status as action_status
             from candidate_events ce
             join workflow_actions wa on wa.candidate_event_id=ce.id
             where ce.event_type like 'HERMES_PROPOSAL_%%'"""
    params: list[Any] = []
    if site:
        sql += " and ce.site=%s"
        params.append(site)
    if status:
        sql += " and ce.status=%s"
        params.append(status)
    sql += " order by ce.created_at desc,ce.id desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {"items": rows, "executionExposed": False}


@owner_router.get("/proposals", dependencies=[Depends(require_owner_request)])
def list_owner_hermes_action_proposals(
    site: Site | None = None,
    status: Literal["PENDING", "VALIDATED", "REJECTED", "APPLIED", "SUPERSEDED"] | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    return list_hermes_action_proposals(site=site, status=status, limit=limit)


@router.post(
    "/proposals/{action_id}/decision",
    dependencies=[Depends(require_hermes_approval_auth)],
)
def decide_hermes_action_proposal(
    action_id: int,
    payload: HermesActionDecisionIn,
) -> dict[str, Any]:
    """Approve or reject staging only; approval does not execute the action."""
    _require_database()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select wa.id as action_id,wa.status as action_status,
                          ce.id as proposal_id,ce.status as candidate_status
                   from workflow_actions wa
                   join candidate_events ce on ce.id=wa.candidate_event_id
                   where wa.id=%s and ce.event_type like 'HERMES_PROPOSAL_%%'
                   for update of wa,ce""",
                (action_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, "Hermes action proposal not found")

            if payload.decision == "APPROVE":
                if row["candidate_status"] == "VALIDATED" and row["action_status"] == "READY":
                    idempotent = True
                elif row["candidate_status"] == "PENDING" and row["action_status"] == "PLANNED":
                    idempotent = False
                    cur.execute(
                        """update candidate_events
                           set status='VALIDATED',validated_at=now(),validated_by=%s,rejection_reason=null
                           where id=%s""",
                        (payload.actor, row["proposal_id"]),
                    )
                    cur.execute(
                        "update workflow_actions set status='READY' where id=%s",
                        (action_id,),
                    )
                else:
                    raise HTTPException(409, "proposal can no longer be approved")
                candidate_status, action_status = "VALIDATED", "READY"
            else:
                if row["candidate_status"] == "REJECTED" and row["action_status"] == "CANCELLED":
                    idempotent = True
                elif row["candidate_status"] == "PENDING" and row["action_status"] == "PLANNED":
                    idempotent = False
                    cur.execute(
                        """update candidate_events
                           set status='REJECTED',validated_at=now(),validated_by=%s,rejection_reason=%s
                           where id=%s""",
                        (payload.actor, payload.note, row["proposal_id"]),
                    )
                    cur.execute(
                        "update workflow_actions set status='CANCELLED' where id=%s",
                        (action_id,),
                    )
                else:
                    raise HTTPException(409, "proposal can no longer be rejected")
                candidate_status, action_status = "REJECTED", "CANCELLED"

            cur.execute(
                """insert into event_audit_log(
                     candidate_event_id,workflow_action_id,action,actor,details
                   ) values (%s,%s,%s,%s,%s::jsonb)""",
                (
                    row["proposal_id"],
                    action_id,
                    f"HERMES_PROPOSAL_{payload.decision}",
                    payload.actor,
                    json.dumps(
                        {"note": payload.note, "idempotent": idempotent, "executed": False},
                        ensure_ascii=False,
                    ),
                ),
            )
        conn.commit()

    return {
        "proposalId": row["proposal_id"],
        "actionId": action_id,
        "decision": payload.decision,
        "candidateStatus": candidate_status,
        "actionStatus": action_status,
        "idempotent": idempotent,
        "executed": False,
        "executionLocked": True,
    }


@owner_router.post(
    "/proposals/{action_id}/decision",
    dependencies=[Depends(require_owner_request)],
)
def decide_owner_hermes_action_proposal(
    action_id: int,
    payload: OwnerHermesActionDecisionIn,
) -> dict[str, Any]:
    return decide_hermes_action_proposal(
        action_id,
        HermesActionDecisionIn(
            decision=payload.decision,
            actor="owner-ui",
            note=payload.note,
        ),
    )
