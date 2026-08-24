from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend.db import connection, database_ready
from backend.gpt_bridge_api import require_gpt_auth
from backend.operational_api import (
    PurchaseOrderCoverageIn,
    PurchaseOrderCreateIn,
    PurchaseOrderItemIn,
    canonical_unit,
    create_purchase_order_record,
    find_active_purchase_order_for_coverage,
)


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


class HermesPoDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_code: str | None = Field(default=None, max_length=160)
    item_name: str = Field(min_length=1, max_length=300)
    planning_snapshot_item_id: int | None = Field(default=None, ge=1)
    planned_qty: float | None = Field(default=None, ge=0)
    po_qty: float = Field(gt=0)
    unit: str | None = Field(default=None, max_length=40)
    planning_price: float | None = Field(default=None, ge=0)
    po_price: float | None = Field(default=None, ge=0)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("item_name")
    @classmethod
    def normalize_item_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("item_name cannot be blank")
        return name


class HermesPoDraftCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_date: date
    cooking_date: date | None = None
    source_planning_snapshot_id: int | None = Field(default=None, ge=1)
    items: list[HermesPoDraftItem] = Field(min_length=1, max_length=300)


class HermesPoDraftPayload(BaseModel):
    """Only operational payload the owner executor is allowed to apply."""

    model_config = ConfigDict(extra="forbid")

    po_code: str = Field(min_length=1, max_length=220)
    distribution_date: date
    cooking_at: datetime | None = None
    source_planning_snapshot_id: int | None = Field(default=None, ge=1)
    status: Literal["DRAFT"] = "DRAFT"
    items: list[HermesPoDraftItem] = Field(min_length=1, max_length=300)
    coverage: list[HermesPoDraftCoverage] = Field(default_factory=list, max_length=31)

    @field_validator("po_code")
    @classmethod
    def normalize_po_code(cls, value: str) -> str:
        code = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{2,219}", code):
            raise ValueError("po_code contains unsupported characters")
        return code

    @model_validator(mode="after")
    def validate_coverage_totals(self) -> "HermesPoDraftPayload":
        if not self.coverage:
            return self
        dates = [row.distribution_date for row in self.coverage]
        if len(set(dates)) != len(dates):
            raise ValueError("coverage distribution_date cannot be duplicated")
        if min(dates) != self.distribution_date:
            raise ValueError("distribution_date must be the first coverage date")

        def key(item: HermesPoDraftItem) -> tuple[str, str]:
            identity = str(item.item_code or item.item_name).strip().upper()
            return identity, str(canonical_unit(item.unit) or "").upper()

        order_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        coverage_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for item in self.items:
            order_totals[key(item)] += Decimal(str(item.po_qty))
        for coverage in self.coverage:
            for item in coverage.items:
                coverage_totals[key(item)] += Decimal(str(item.po_qty))
        if order_totals != coverage_totals:
            raise ValueError("aggregate items must exactly match coverage item quantities")
        return self

    def to_purchase_order(self, *, site: Site, vendor_code: str) -> PurchaseOrderCreateIn:
        return PurchaseOrderCreateIn(
            po_code=self.po_code,
            site=site,
            vendor_code=vendor_code,
            distribution_date=self.distribution_date,
            cooking_at=self.cooking_at,
            source_planning_snapshot_id=self.source_planning_snapshot_id,
            status="DRAFT",
            items=[PurchaseOrderItemIn(**item.model_dump()) for item in self.items],
            coverage=[
                PurchaseOrderCoverageIn(
                    distribution_date=row.distribution_date,
                    cooking_date=row.cooking_date,
                    source_planning_snapshot_id=row.source_planning_snapshot_id,
                    items=[PurchaseOrderItemIn(**item.model_dump()) for item in row.items],
                )
                for row in self.coverage
            ],
        )


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

    @model_validator(mode="after")
    def validate_executable_po_contract(self) -> "HermesActionProposalIn":
        if self.action_type != "CREATE_PO":
            return self
        if self.target_type != "purchase_order":
            raise ValueError("CREATE_PO target_type must be purchase_order")
        if self.target_id is not None:
            raise ValueError("CREATE_PO proposal must not target an existing purchase order")
        if not str(self.vendor_code or "").strip():
            raise ValueError("CREATE_PO proposal requires vendor_code")
        draft = HermesPoDraftPayload.model_validate(self.payload)
        expected_prefix = f"PO-{self.site}-{draft.distribution_date.strftime('%Y%m%d')}"
        if not draft.po_code.startswith(expected_prefix):
            raise ValueError(f"CREATE_PO po_code must start with {expected_prefix}")
        self.vendor_code = str(self.vendor_code).strip().upper()
        self.payload = draft.model_dump(mode="json")
        return self


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
    role = str(getattr(request.state, "sppg_role", "")).upper()
    auth_kind = str(getattr(request.state, "sppg_auth_kind", "")).upper()
    if role != "OWNER" or auth_kind != "SESSION":
        raise HTTPException(403, "OWNER browser session required")


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


def _load_hermes_action(cur: Any, action_id: int, *, for_update: bool = False) -> dict[str, Any]:
    lock_clause = " for update of wa,ce" if for_update else ""
    cur.execute(
        """select wa.id as action_id,wa.status as action_status,wa.action_type,
                  wa.target_type,wa.target_id,wa.action_payload,wa.idempotency_key,
                  wa.applied_at,wa.applied_by,
                  ce.id as proposal_id,ce.status as candidate_status,ce.site,
                  ce.vendor_code,ce.entity_code,ce.payload as candidate_payload,
                  ce.raw_text,ce.event_type
           from workflow_actions wa
           join candidate_events ce on ce.id=wa.candidate_event_id
           where wa.id=%s and ce.event_type like 'HERMES_PROPOSAL_%%'""" + lock_clause,
        (action_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "Hermes action proposal not found")
    return dict(row)


def _po_draft_from_action(row: dict[str, Any]) -> tuple[HermesPoDraftPayload, PurchaseOrderCreateIn]:
    if row.get("action_type") != "CREATE_PO" or row.get("event_type") != "HERMES_PROPOSAL_CREATE_PO":
        raise HTTPException(409, "executor only supports CREATE_PO")
    if row.get("target_type") != "purchase_order":
        raise HTTPException(409, "CREATE_PO target_type must be purchase_order")
    if row.get("target_id") not in {None, ""} and row.get("action_status") != "APPLIED":
        raise HTTPException(409, "CREATE_PO cannot target an existing purchase order")

    action_payload = row.get("action_payload") or {}
    if isinstance(action_payload, str):
        try:
            action_payload = json.loads(action_payload)
        except ValueError as exc:
            raise HTTPException(409, "stored CREATE_PO action payload is not valid JSON") from exc
    raw_payload = action_payload.get("payload") if isinstance(action_payload, dict) else None
    try:
        draft = HermesPoDraftPayload.model_validate(raw_payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(value) for value in first.get("loc", [])) or "payload"
        message = str(first.get("msg") or "invalid payload")
        raise HTTPException(409, f"CREATE_PO payload invalid at {location}: {message}") from exc

    site = str(row.get("site") or "").upper().strip()
    vendor = str(row.get("vendor_code") or "").upper().strip()
    if site not in {"MAJA", "CEMPLANG"} or not vendor:
        raise HTTPException(409, "CREATE_PO proposal is missing site or vendor")
    expected_prefix = f"PO-{site}-{draft.distribution_date.strftime('%Y%m%d')}"
    if not draft.po_code.startswith(expected_prefix):
        raise HTTPException(409, f"CREATE_PO po_code must start with {expected_prefix}")
    return draft, draft.to_purchase_order(site=site, vendor_code=vendor)


def _validate_po_references(cur: Any, row: dict[str, Any], draft: HermesPoDraftPayload) -> None:
    site = str(row["site"]).upper()
    vendor = str(row["vendor_code"]).upper()
    cur.execute(
        """select code,entity_type from entities
           where code=%s and active=true and entity_type in ('VENDOR','INTERNAL_ORG')""",
        (vendor,),
    )
    if cur.fetchone() is None:
        raise HTTPException(409, f"vendor {vendor} is not an active PO supplier")
    cur.execute("select code from sites where code=%s and active=true", (site,))
    if cur.fetchone() is None:
        raise HTTPException(409, f"site {site} is not active")

    expected_snapshots: dict[int, date] = {}
    if draft.source_planning_snapshot_id is not None:
        expected_snapshots[draft.source_planning_snapshot_id] = draft.distribution_date
    for coverage in draft.coverage:
        if coverage.source_planning_snapshot_id is not None:
            expected_snapshots[coverage.source_planning_snapshot_id] = coverage.distribution_date
    if expected_snapshots:
        ids = sorted(expected_snapshots)
        cur.execute(
            """select id,site,distribution_date,status
               from planning_snapshots where id=any(%s)""",
            (ids,),
        )
        snapshots = {int(value["id"]): value for value in cur.fetchall()}
        missing = [value for value in ids if value not in snapshots]
        if missing:
            raise HTTPException(409, f"planning snapshot not found: {missing[0]}")
        for snapshot_id, expected_date in expected_snapshots.items():
            snapshot = snapshots[snapshot_id]
            if str(snapshot.get("site") or "").upper() != site:
                raise HTTPException(409, f"planning snapshot {snapshot_id} belongs to another site")
            if snapshot.get("distribution_date") != expected_date:
                raise HTTPException(409, f"planning snapshot {snapshot_id} has a different distribution date")
            if str(snapshot.get("status") or "").upper() == "REJECTED":
                raise HTTPException(409, f"planning snapshot {snapshot_id} is rejected")

    item_ids = {
        int(item.planning_snapshot_item_id)
        for item in draft.items
        if item.planning_snapshot_item_id is not None
    }
    coverage_item_dates: dict[int, date] = {}
    for coverage in draft.coverage:
        for item in coverage.items:
            if item.planning_snapshot_item_id is not None:
                coverage_item_dates[int(item.planning_snapshot_item_id)] = coverage.distribution_date
                item_ids.add(int(item.planning_snapshot_item_id))
    if item_ids:
        cur.execute(
            """select psi.id,ps.site,ps.distribution_date,ps.status
               from planning_snapshot_items psi
               join planning_snapshots ps on ps.id=psi.planning_snapshot_id
               where psi.id=any(%s)""",
            (sorted(item_ids),),
        )
        items = {int(value["id"]): value for value in cur.fetchall()}
        missing = [value for value in sorted(item_ids) if value not in items]
        if missing:
            raise HTTPException(409, f"planning snapshot item not found: {missing[0]}")
        for item_id, item in items.items():
            if str(item.get("site") or "").upper() != site:
                raise HTTPException(409, f"planning snapshot item {item_id} belongs to another site")
            expected_date = coverage_item_dates.get(item_id)
            if expected_date is not None and item.get("distribution_date") != expected_date:
                raise HTTPException(409, f"planning snapshot item {item_id} has a different coverage date")
            if str(item.get("status") or "").upper() == "REJECTED":
                raise HTTPException(409, f"planning snapshot item {item_id} belongs to a rejected snapshot")


def _po_preview_payload(
    row: dict[str, Any],
    draft: HermesPoDraftPayload,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "proposalId": row["proposal_id"],
        "actionId": row["action_id"],
        "candidateStatus": row["candidate_status"],
        "actionStatus": row["action_status"],
        "executable": existing is None,
        "blockedByExistingPurchaseOrder": existing is not None,
        "existingPurchaseOrder": (
            {
                "purchaseOrderId": existing.get("id"),
                "poCode": existing.get("po_code"),
                "revisionNo": existing.get("revision_no"),
                "status": existing.get("status"),
                "coverageDates": existing.get("coverage_dates") or [],
            }
            if existing
            else None
        ),
        "draft": {
            "site": row["site"],
            "vendor_code": row["vendor_code"],
            **draft.model_dump(mode="json"),
        },
        "safety": {
            "createsStatus": "DRAFT",
            "finalizesPurchaseOrder": False,
            "marksPurchaseOrderSent": False,
            "sendsWhatsApp": False,
            "writesFinance": False,
            "writesReceiving": False,
        },
    }


def _audit_po_execution_failure(action_id: int, detail: str) -> None:
    """Best-effort audit after a failed transaction; workflow state stays READY."""
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                row = _load_hermes_action(cur, action_id)
                cur.execute(
                    """insert into event_audit_log(
                         candidate_event_id,workflow_action_id,action,actor,details
                       ) values (%s,%s,'HERMES_CREATE_PO_DRAFT_FAILED','owner-ui',%s::jsonb)""",
                    (
                        row["proposal_id"],
                        action_id,
                        json.dumps(
                            {
                                "detail": str(detail)[:500],
                                "candidateStatus": row["candidate_status"],
                                "actionStatus": row["action_status"],
                                "workflowStateChanged": False,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            conn.commit()
    except Exception:
        # Never mask the primary execution error with an audit write failure.
        return


@router.get("/status", dependencies=[Depends(require_gpt_auth)])
def hermes_action_status() -> dict[str, Any]:
    return {
        "databaseReady": database_ready(),
        "proposalWritesExposed": True,
        "approvalConfigured": bool(os.getenv("SPPG_HERMES_APPROVAL_KEY", "").strip()),
        "executionExposed": False,
        "mode": "PROPOSE_AND_APPROVE_ONLY",
        "ownerExecutionCapabilities": ["CREATE_PO_DRAFT"],
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
                    wa.action_payload,wa.status as action_status,wa.applied_at,wa.applied_by
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
    result = list_hermes_action_proposals(site=site, status=status, limit=limit)
    return {
        **result,
        "ownerExecutionCapabilities": ["CREATE_PO_DRAFT"],
        "genericExecutionExposed": False,
    }


@owner_router.get(
    "/proposals/{action_id}/po-draft-preview",
    dependencies=[Depends(require_owner_request)],
)
def preview_owner_hermes_po_draft(action_id: int) -> dict[str, Any]:
    """Validate and preview exact PO data without writing operational records."""
    _require_database()
    with connection() as conn:
        with conn.cursor() as cur:
            row = _load_hermes_action(cur, action_id)
            if row["candidate_status"] != "VALIDATED" or row["action_status"] != "READY":
                raise HTTPException(409, "CREATE_PO must be VALIDATED / READY before preview")
            draft, purchase_order = _po_draft_from_action(row)
            _validate_po_references(cur, row, draft)
            coverage_dates = [value.distribution_date for value in purchase_order.coverage] or [purchase_order.distribution_date]
            existing = find_active_purchase_order_for_coverage(
                cur,
                site=purchase_order.site,
                vendor=purchase_order.vendor_code,
                coverage_dates=coverage_dates,
            )
    return _po_preview_payload(row, draft, existing)


@owner_router.post(
    "/proposals/{action_id}/create-po-draft",
    dependencies=[Depends(require_owner_request)],
)
def execute_owner_hermes_po_draft(action_id: int) -> dict[str, Any]:
    """Apply only an approved CREATE_PO action, and create only a DRAFT PO."""
    _require_database()
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                row = _load_hermes_action(cur, action_id, for_update=True)
                if row["candidate_status"] == "APPLIED" and row["action_status"] == "APPLIED":
                    if not row.get("target_id"):
                        raise HTTPException(409, "applied action has no purchase order target")
                    cur.execute(
                        """select id,po_code,revision_no,status
                           from purchase_orders where id=%s""",
                        (int(row["target_id"]),),
                    )
                    existing_target = cur.fetchone()
                    if existing_target is None:
                        raise HTTPException(409, "applied action purchase order target is missing")
                    return {
                        "proposalId": row["proposal_id"],
                        "actionId": action_id,
                        "candidateStatus": "APPLIED",
                        "actionStatus": "APPLIED",
                        "purchaseOrderId": existing_target["id"],
                        "poCode": existing_target["po_code"],
                        "revisionNo": existing_target["revision_no"],
                        "purchaseOrderStatus": existing_target["status"],
                        "createdNow": False,
                        "idempotent": True,
                        "draftOnlyAtCreation": True,
                        "finalizedByExecutor": False,
                        "markedSentByExecutor": False,
                        "whatsAppSentByExecutor": False,
                        "otherExecutorsLocked": True,
                    }
                if row["candidate_status"] != "VALIDATED" or row["action_status"] != "READY":
                    raise HTTPException(409, "CREATE_PO must be VALIDATED / READY before execution")

                draft, purchase_order = _po_draft_from_action(row)
                _validate_po_references(cur, row, draft)
                source_hash = hashlib.sha256(
                    f"hermes-create-po-draft:{row['idempotency_key']}".encode("utf-8")
                ).hexdigest()
                result = create_purchase_order_record(
                    cur,
                    purchase_order,
                    provenance={
                        "source_type": "HERMES_APPROVED",
                        "source_external_id": f"workflow-action:{action_id}",
                        "source_hash": source_hash,
                        "source_raw_text": str(row.get("raw_text") or "")[:10000],
                    },
                )
                if result.get("alreadyExists"):
                    raise HTTPException(
                        409,
                        f"active PO already exists: {result.get('poCode')} ({result.get('status')})",
                    )
                if result.get("status") != "DRAFT":
                    raise HTTPException(500, "PO executor violated DRAFT-only boundary")

                purchase_order_id = int(result["purchaseOrderId"])
                cur.execute(
                    """update workflow_actions
                       set status='APPLIED',target_id=%s,applied_at=now(),applied_by='owner-ui'
                       where id=%s and status='READY'""",
                    (str(purchase_order_id), action_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(409, "workflow action changed before PO draft could be recorded")
                cur.execute(
                    """update candidate_events
                       set status='APPLIED'
                       where id=%s and status='VALIDATED'""",
                    (row["proposal_id"],),
                )
                if cur.rowcount != 1:
                    raise HTTPException(409, "candidate event changed before PO draft could be recorded")
                cur.execute(
                    """insert into event_audit_log(
                         candidate_event_id,workflow_action_id,action,actor,details
                       ) values (%s,%s,'HERMES_CREATE_PO_DRAFT_APPLIED','owner-ui',%s::jsonb)""",
                    (
                        row["proposal_id"],
                        action_id,
                        json.dumps(
                            {
                                "purchaseOrderId": purchase_order_id,
                                "poCode": result["poCode"],
                                "revisionNo": result["revisionNo"],
                                "createdStatus": "DRAFT",
                                "finalized": False,
                                "markedSent": False,
                                "whatsAppSent": False,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            conn.commit()
    except HTTPException as exc:
        _audit_po_execution_failure(action_id, str(exc.detail))
        raise
    except Exception as exc:
        _audit_po_execution_failure(action_id, exc.__class__.__name__)
        raise

    return {
        "proposalId": row["proposal_id"],
        "actionId": action_id,
        "candidateStatus": "APPLIED",
        "actionStatus": "APPLIED",
        "purchaseOrderId": result["purchaseOrderId"],
        "poCode": result["poCode"],
        "revisionNo": result["revisionNo"],
        "purchaseOrderStatus": "DRAFT",
        "createdNow": True,
        "idempotent": False,
        "draftOnlyAtCreation": True,
        "finalizedByExecutor": False,
        "markedSentByExecutor": False,
        "whatsAppSentByExecutor": False,
        "otherExecutorsLocked": True,
    }


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
