"""Server-enforced, one-time, UI-approved SPPG operational changes.

All mutations are scoped to the existing OWNER OAuth bearer gate. Only an
MCP Apps app-visible confirmation tool executes a prepared operation.
Approvals and outcomes are persisted in PostgreSQL for replay protection and
an audit trail. The "commit=true" value is constructed server-side.
"""
from __future__ import annotations

import asyncio
import time
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.vendor_payables_manual_api import (
    ManualPayableIn, preview_manual_payable, commit_manual_payable,
)
from plugin_mcp.core_proxy import core_request, operational_writes_enabled
from plugin_mcp.form_fields import describe_form, apply_form
from plugin_mcp.receipt_fastpath import normalize_receipt_input, compact_knowledge
from plugin_mcp.confirmation_evidence import confirmation_evidence

audit_logger = logging.getLogger('sppg_confirmation')


OWNER = "SPPG_OWNER"
TTL_MINUTES = 10
# Only these specific workflows can be submitted for a destructive commit.
ACTION_MAP = {
    "CREATE_PO": "CREATE_PURCHASE_ORDER",
    "EDIT_DRAFT_PO": "EDIT_DRAFT_PURCHASE_ORDER",
    "REVISE_PO": "REVISE_PURCHASE_ORDER",
    "CANCEL_PO": "CANCEL_PURCHASE_ORDER",
    "FINALIZE_PO": "FINALIZE_PURCHASE_ORDER",
    "MARK_PO_SENT": "MARK_PURCHASE_ORDER_SENT",
}
EXTRA_ACTIONS = {
    "DELETE_DRAFT_PO", "IMPORT_WHATSAPP_PO", "CREATE_NO_PO_PAYABLE",
    "CREATE_ACCOUNTANT_TRANSACTIONS", "UPDATE_ACCOUNTANT_TRANSACTION",
    "RECORD_GOODS_RECEIPT", "RECORD_STOCK_OPNAME",
    "CREATE_PAYABLE_FROM_RECEIPT", "RECORD_VENDOR_PAYMENT",
    "RECONCILE_VENDOR_PAYMENT",
    "UPSERT_INVENTORY_ITEM_MASTER",
}
CONTROL_ACTIONS = frozenset(ACTION_MAP) | EXTRA_ACTIONS
DESTRUCTIVE_ACTIONS = frozenset({"DELETE_DRAFT_PO", "CANCEL_PO", "REVISE_PO"})
PO_ACTIONS_WITH_SNAPSHOT = frozenset({
    "EDIT_DRAFT_PO", "REVISE_PO", "CANCEL_PO", "FINALIZE_PO", "MARK_PO_SENT", "DELETE_DRAFT_PO",
})


class ChangeRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=1000)
    site: Literal["MAJA", "CEMPLANG", "GLOBAL"]


def _hash_json(value: Any) -> str:
    clean = json.dumps(jsonable_encoder(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _db_ready() -> None:
    if not database_ready():
        raise RuntimeError("PostgreSQL unavailable; approval gate is closed")


def _ensure_table(cur: Any) -> None:
    cur.execute(
        """
        create table if not exists sppg_mcp_approvals (
            id uuid primary key,
            operator_sub text not null,
            site text not null,
            action text not null,
            reason text not null,
            proposed_payload jsonb not null,
            before_state jsonb,
            before_hash text,
            preview_data jsonb not null,
            impact_data jsonb not null,
            status text not null default 'PENDING',
            created_at timestamptz not null default now(),
            expires_at timestamptz not null,
            confirmed_at timestamptz,
            executed_at timestamptz,
            result_data jsonb,
            error_message text
        )
        """
    )
    cur.execute('alter table sppg_mcp_approvals add column if not exists confirmation_received_at timestamptz')
    cur.execute('alter table sppg_mcp_approvals add column if not exists last_confirmation_outcome jsonb')


def _confirmation_outcome(cur, approval_id, status, reason=None):
    """Persist only audit evidence; this never executes a domain mutation."""
    value = {'status': status, 'recordedAt': datetime.now(timezone.utc).isoformat()}
    if reason:
        value['reason'] = str(reason)[:1200]
    cur.execute('''update sppg_mcp_approvals
        set confirmation_received_at=coalesce(confirmation_received_at,now()),
            last_confirmation_outcome=%s::jsonb where id=%s and operator_sub=%s''',
        (json.dumps(value), approval_id, OWNER))
    audit_logger.info('confirmation approvalId=%s outcome=%s', approval_id, status)


def _save_confirmation_outcome(approval_id, status, reason=None):
    with connection() as conn:
        with conn.cursor() as cur:
            _confirmation_outcome(cur, approval_id, status, reason)
        conn.commit()


async def _read_po(po_id: int) -> dict[str, Any]:
    if po_id <= 0:
        raise ValueError("purchase_order_id must be positive")
    return await core_request("GET", f"/v1/purchase-orders/{po_id}")


async def _preview(change: ChangeRequest) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    action, data = change.action, dict(change.payload)
    if action not in CONTROL_ACTIONS:
        raise ValueError("Action not in the confirmed-write allowlist")
    if change.site=='GLOBAL' and action!='UPSERT_INVENTORY_ITEM_MASTER':
        raise ValueError('GLOBAL is only allowed for the shared inventory master')
    if "site" in data and data["site"] != change.site:
        raise ValueError("Cross-site payload and change.site mismatch")
    data.pop("commit", None)

    before = None
    if action in PO_ACTIONS_WITH_SNAPSHOT:
        po_id = int(data.get("purchase_order_id") or 0)
        before = await _read_po(po_id)
        po_site = str(before.get("site") or before.get("result", {}).get("site") or "").upper()
        if po_site != change.site:
            raise ValueError("PO site does not match the requested site")
    if action == "UPSERT_INVENTORY_ITEM_MASTER":
        data.pop('site',None)
        allowed={'code','canonical_name','category_code','base_unit','aliases','metadata','active','expected_before_hash','require_unchanged','require_unit'}
        if set(data)-allowed:
            raise ValueError('Unknown inventory master fields: '+', '.join(sorted(set(data)-allowed)))
        result=await core_request('POST','/v1/inventory/items',json_body={**data,'commit':False,'require_unit':True})
        before=result.get('before')
        impact={'master':'GLOBAL_SHARED_MAJA_CEMPLANG','aliases':'ADD/PRESERVE; CONFLICTS REJECTED',
                'stock':'NONE','finance':'NONE','note':'Master defaults are shared across both sites. Existing SO/receiving quantities are not rewritten.'}
    elif action == "CREATE_ACCOUNTANT_TRANSACTIONS":
        from backend.gpt_bridge_api import FinanceTransactionBatchIn
        data["site"] = change.site
        unknown_payment = any("payment_status" not in row and "is_debt" not in row for row in data.get("items",[]))
        batch = FinanceTransactionBatchIn.model_validate(data)
        totals = {"income": 0.0, "expense": 0.0, "unpaidExpense": 0.0}
        for line in batch.items:
            totals[line.type] += float(line.amount)
            if line.type == "expense" and (line.is_debt or line.payment_status in {"unpaid", "partial"}):
                totals["unpaidExpense"] += float(line.amount) - float(line.paid_amount or 0)
        result = {
            "canCommit": True, "committed": False, "site": change.site,
            "sourceRef": batch.source_ref, "itemCount": len(batch.items),
            **({"canCommit":False,"validationError":"Pilih status pembayaran sebelum menyimpan."} if unknown_payment else {}),
            "items": [item.model_dump(mode="json") for item in batch.items],
            "totals": {key: round(value, 2) for key, value in totals.items()},
            "note": "Commit may write PostgreSQL and separately synchronize Firestore.",
        }
        impact = {
            "accountant": f"CREATE {len(batch.items)} FINANCE TRANSACTIONS",
            "firestore": "SYNC ATTEMPT; response status must be checked",
            "stock": "NONE",
            "duplicate": "Source_ref and canonical item data provide idempotency.",
        }
    elif action == "UPDATE_ACCOUNTANT_TRANSACTION":
        from backend.gpt_bridge_api import FinanceTransactionPatchIn
        tx_id = str(data.get("transaction_id") or "").strip()
        if not tx_id:
            raise ValueError("transaction_id required")
        patch = dict(data.get("patch") or {})
        if not patch:
            raise ValueError("nonempty patch required")
        validated = FinanceTransactionPatchIn.model_validate(patch)
        found = await core_request("GET", "/v1/gpt/finance-transactions", params={
            "site": change.site, "q": tx_id, "limit": 100,
        })
        matches = [r for r in found.get("items", []) if str(r.get("transaction_id")) == tx_id]
        if len(matches) != 1:
            raise ValueError("Target Accountant transaction must exist exactly once in the selected site")
        before = matches[0]
        result = {
            "canCommit": True, "committed": False, "site": change.site,
            "transactionId": tx_id, "fieldsChanged": validated.model_dump(exclude_unset=True, mode="json"),
        }
        impact = {
            "accountant": f"UPDATE TRANSACTION {tx_id}",
            "firestore": "MAY RESYNC THE SAME DOCUMENT",
            "stock": "NONE",
            "beforeAmount": before.get("amount"),
            "afterAmount": patch.get("amount", before.get("amount")),
        }
    elif action == "RECORD_GOODS_RECEIPT":
        data["site"] = change.site
        result = await core_request("POST", "/v1/receiving/whatsapp", json_body={**data, "commit": False})
        result.pop("confirmationToken", None)
        impact = {
            "goodsReceipt": "CREATE/UPDATE RECEIVING",
            "stock": "ACCEPTED QUANTITIES MAY BE POSTED TO WAREHOUSE",
            "finance": "NONE",
            "caution": "Do not double-post receipts already entered manually.",
        }
        if result.get('receiptState')=='POSSIBLE_DUPLICATE':
            impact={'goodsReceipt':'NONE: REVIEW EXISTING RECEIPT','stock':'NONE','finance':'NONE'}
    elif action == "RECORD_STOCK_OPNAME":
        data["location"] = change.site
        result = await core_request(
            "POST", "/v1/inventory/stock-opname/whatsapp", json_body={**data, "commit": False},
        )
        impact = {
            "stock": "NEW PHYSICAL BASELINE replaces the previous SO baseline",
            "finance": "NONE", "po": "Future stock projections and PO recommendations may change.",
        }
    elif action == "CREATE_PAYABLE_FROM_RECEIPT":
        data["site"] = change.site
        result = await core_request(
            "POST", "/v1/vendor-payables/from-receipt", json_body={**data, "commit": False},
        )
        impact = {
            "vendorPayable": "CREATE UNPAID INVOICE",
            "stock": "NONE", "finance": "NONE",
            "note": "PO and goods receipt IDs must exist and match the site.",
        }
    elif action == "RECORD_VENDOR_PAYMENT":
        data["site"] = change.site
        result = await core_request(
            "POST", "/v1/vendor-payments/record-evidence", json_body={**data, "commit": False},
        )
        impact = {
            "vendorPayment": "RECORD PAID TRANSFER",
            "finance": "IMPORTANT: AUTO CREATES AN ACCOUNTANT EXPENSE",
            "firestore": "SYNC ATTEMPT TO ACCOUNTANT; inspect final status",
            "stock": "NONE",
            "warning": "Do not also create another manual Accountant expense for this transfer.",
        }
    elif action == "RECONCILE_VENDOR_PAYMENT":
        payment_id = int(data.get("payment_id") or 0)
        if payment_id <= 0:
            raise ValueError("payment_id must be positive")
        result = await core_request(
            "POST", f"/v1/vendor-payments/{payment_id}/reconcile",
            json_body={
                "vendor_invoice_id": data.get("vendor_invoice_id"),
                "note": data.get("note", ""),
                "actor": "sppg-control-room",
                "commit": False,
            },
        )
        if str(result.get("site") or "").upper() != change.site:
            raise ValueError("Payment does not belong to selected site")
        impact = {
            "vendorPayment": "RECONCILE EXISTING PAID TRANSFER",
            "finance": "DO NOT CREATE A SECOND PAYMENT OR EXPENSE",
            "stock": "NONE",
        }
    elif action == "CREATE_NO_PO_PAYABLE":
        data["site"] = change.site
        manual = ManualPayableIn.model_validate({**data, "commit": False})
        result = preview_manual_payable(manual)
        impact = {
            "stock": "NONE", "finance": "NO LEDGER TRANSACTION",
            "vendorPayable": "CREATE UNPAID", "noPoException": True,
            "note": "Only a payable is created, no PO, receipt, or stock adjustment.",
        }
    elif action == "IMPORT_WHATSAPP_PO":
        data["site"] = change.site
        if not str(data.get("source_raw_text") or "").strip():
            raise ValueError("Original WhatsApp evidence text is required")
        body = {**data, "commit": False}
        result = await core_request("POST", "/v1/operations/history/import", json_body=body)
        impact = {
            "purchaseOrder": "HISTORICAL IMPORT",
            "stock": "NO AUTOMATIC INVENTORY POSTING",
            "finance": "NONE",
            "receipt": "Only if actual received_qty was explicitly documented.",
        }
    elif action == "DELETE_DRAFT_PO":
        status = str(before.get("status") or before.get("result", {}).get("status") or "").upper()
        if status != "DRAFT":
            raise ValueError("Hard-delete is restricted to unsent DRAFT PO")
        result = {
            "canCommit": True,
            "committed": False,
            "purchaseOrderId": data["purchase_order_id"],
            "statusBefore": status,
            "operation": "DELETE_DRAFT_PO",
        }
        impact = {
            "purchaseOrder": "DELETE DRAFT",
            "stock": "NONE if no linked receipt",
            "finance": "NONE",
            "warning": "The backend rechecks that no goods receipt exists.",
        }
    else:
        if action == "CREATE_PO":
            data["site"] = change.site
        result = await core_request(
            "POST", "/v1/gpt/operations/execute",
            json_body={"operation": ACTION_MAP[action], "payload": data, "commit": False},
        )
        impact = {
            "purchaseOrder": action,
            "stock": "NO DIRECT STOCK MUTATION FOR PO CHANGES",
            "finance": "NONE",
            "note": "Backend status, receiving, and revision constraints are checked again on commit.",
        }
    return result, before, impact


def _render_pending(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "approvalId": str(row["id"]),
        "status": row["status"],
        "action": row["action"],
        "site": row["site"],
        "reason": row["reason"],
        "preview": row["preview_data"],
        "before": row.get("before_state"),
        "impact": row["impact_data"],
        "expiresAt": row["expires_at"].isoformat() if isinstance(row["expires_at"], datetime) else str(row["expires_at"]),
        "approvalMethod": "NATIVE_CHAT_CHOICE_OR_TEXT",
        "form": describe_form(row["action"], row["proposed_payload"], row["preview_data"]),
        "isDestructive": row["action"] in DESTRUCTIVE_ACTIONS,
        "writeEnabled": operational_writes_enabled(),
        "message": "Please check this card. Only explicit operator confirmation may commit.",
    }


async def prepare_change(action: str, payload: dict[str, Any], site: str, reason: str) -> dict[str, Any]:
    change = ChangeRequest.model_validate({
        "action": action,
        "payload": payload,
        "site": site,
        "reason": reason,
    })
    # Prepare is intentionally available before the production switch is on.
    if action not in CONTROL_ACTIONS:
        raise ValueError("Action not in the confirmed-write allowlist")
    if site=='GLOBAL' and action!='UPSERT_INVENTORY_ITEM_MASTER':
        raise ValueError('GLOBAL is only allowed for the shared inventory master')
    if payload.get("site",site) != site:
        raise ValueError("Cross-site payload and change.site mismatch")
    started = time.monotonic()
    normalization_error = None
    if action == "RECORD_GOODS_RECEIPT":
        try:
            change.payload = normalize_receipt_input(change.payload)
        except ValueError as exc:
            normalization_error = str(exc)

    async def preview_once():
        if normalization_error:
            return {"canCommit":False,"validationError":normalization_error},None,{}
        try:
            return await _preview(change)
        except Exception as exc:
            return {"canCommit":False,"validationError":str(exc)[:800]},None,{}

    async def knowledge_once():
        try:
            body=await asyncio.wait_for(core_request("GET","/v1/gpt/operational-context",params={
                "site":None if action=='UPSERT_INVENTORY_ITEM_MASTER' else site,"vendor":change.payload.get("vendor_code"),"q":"","limit":6,
                "asOf":str(change.payload.get("received_at") or "")[:10] or None,
            }), timeout=2.0)
            return compact_knowledge(body)
        except Exception as exc:
            return {"loaded":False,"error":str(exc)[:160]}

    (preview,before,impact),knowledge = await asyncio.gather(preview_once(),knowledge_once())
    if action=='UPSERT_INVENTORY_ITEM_MASTER' and preview.get('expectedBeforeHash'):
        change.payload['expected_before_hash']=preview['expectedBeforeHash']
        change.payload['require_unchanged']=True
        change.payload['require_unit']=True
    duplicate_review=preview.get('receiptState')=='POSSIBLE_DUPLICATE'
    status = "POSSIBLE_DUPLICATE" if duplicate_review else ("DRAFT" if preview.get("canCommit") is False else "PENDING")
    _db_ready()
    proposal_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TTL_MINUTES)
    before_hash = _hash_json(before) if before is not None else None
    with connection() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute(
                """insert into sppg_mcp_approvals(
                    id,operator_sub,site,action,reason,proposed_payload,before_state,before_hash,
                    preview_data,impact_data,expires_at,status
                   ) values (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                (
                    proposal_id, OWNER, change.site, change.action, change.reason,
                    json.dumps(change.payload, ensure_ascii=False, default=str),
                    json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
                    before_hash, json.dumps(preview, ensure_ascii=False, default=str),
                    json.dumps(impact, ensure_ascii=False, default=str), expires_at, status,
                ),
            )
            conn.commit()
    return {
        "approvalId": str(proposal_id),
        "status": status,
        "action": action,
        "site": change.site,
        "reason": reason,
        "preview": preview,
        "before": before,
        "impact": impact,
        "expiresAt": expires_at.isoformat(),
        "approvalMethod": "NATIVE_CHAT_CHOICE_OR_TEXT",
        "form": describe_form(action, change.payload, preview),
        "isDestructive": action in DESTRUCTIVE_ACTIONS,
        "writeEnabled": operational_writes_enabled(),
        "message": ("Existing receiving found. Show its receipt ID and details; do not ask to commit this report again. No operational record changed." if duplicate_review else "Preview prepared; no operational record changed. Render native ChatGPT choices; wait for a NEW user confirmation before executing."),
        "runtimeKnowledge":knowledge,
        "receiptInput":change.payload.get("receipt_input_summary"),
        "receivedTimePrecision":change.payload.get("received_time_precision"),
        "timingMs":{"prepare":round((time.monotonic()-started)*1000)},
        "nextStep":("Show existing receipt ID(s), not a missing PO error or another save confirmation. A genuinely additional delivery needs distinct operator-supplied evidence." if duplicate_review else "Show this proposal now; do not preview or fetch runtime context again. Wait for explicit operator approval."),
    }


def read_change(approval_id: str) -> dict[str, Any]:
    _db_ready()
    with connection() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute("select * from sppg_mcp_approvals where id=%s and operator_sub=%s", (approval_id, OWNER))
            row = cur.fetchone()
            if not row:
                raise ValueError("Approval request not found")
            evidence = confirmation_evidence(row)
            evidence['canConfirm'] = evidence['canConfirm'] and operational_writes_enabled()
            return {**_render_pending(row), "result": row.get("result_data"), "error": row.get("error_message"), 'confirmationEvidence': evidence}


async def _execute(change: ChangeRequest) -> dict[str, Any]:
    data = dict(change.payload)
    data.pop("commit", None)
    if change.action=='UPSERT_INVENTORY_ITEM_MASTER':
        data.pop('site',None)
        if not data.get('expected_before_hash'):
            raise ValueError('A reviewed master snapshot is required before commit')
        return await core_request('POST','/v1/inventory/items',json_body={**data,'commit':True,'require_unchanged':True,'require_unit':True})
    if change.action == "CREATE_ACCOUNTANT_TRANSACTIONS":
        return await core_request("POST", "/v1/gpt/finance-transactions", json_body={
            **data, "site": change.site,
        })
    if change.action == "UPDATE_ACCOUNTANT_TRANSACTION":
        tx_id = str(data.pop("transaction_id"))
        patch = dict(data.get("patch") or {})
        patch["actor"] = "sppg-control-room"
        return await core_request(
            "PATCH", f"/v1/gpt/finance-transactions/{tx_id}", json_body=patch,
        )
    if change.action == "RECORD_GOODS_RECEIPT":
        return await core_request("POST", "/v1/receiving/whatsapp", json_body={
            **data, "site": change.site, "commit": True,
        })
    if change.action == "RECORD_STOCK_OPNAME":
        return await core_request("POST", "/v1/inventory/stock-opname/whatsapp", json_body={
            **data, "location": change.site, "commit": True,
        })
    if change.action == "CREATE_PAYABLE_FROM_RECEIPT":
        return await core_request("POST", "/v1/vendor-payables/from-receipt", json_body={
            **data, "site": change.site, "commit": True,
        })
    if change.action == "RECORD_VENDOR_PAYMENT":
        return await core_request("POST", "/v1/vendor-payments/record-evidence", json_body={
            **data, "site": change.site, "commit": True,
        })
    if change.action == "RECONCILE_VENDOR_PAYMENT":
        payment_id = int(data.pop("payment_id"))
        return await core_request(
            "POST", f"/v1/vendor-payments/{payment_id}/reconcile",
            json_body={
                "vendor_invoice_id": data.get("vendor_invoice_id"),
                "note": data.get("note", ""),
                "actor": "sppg-control-room",
                "commit": True,
            },
        )
    if change.action == "CREATE_NO_PO_PAYABLE":
        model = ManualPayableIn.model_validate({**data, "site": change.site, "commit": False})
        return commit_manual_payable(model)
    if change.action == "IMPORT_WHATSAPP_PO":
        return await core_request("POST", "/v1/operations/history/import", json_body={
            **data, "site": change.site, "commit": True,
        })
    if change.action == "DELETE_DRAFT_PO":
        return await core_request("DELETE", f"/v1/purchase-orders/{int(data['purchase_order_id'])}")
    if change.action in ACTION_MAP:
        if change.action == "CREATE_PO":
            data["site"] = change.site
        return await core_request("POST", "/v1/gpt/operations/execute", json_body={
            "operation": ACTION_MAP[change.action], "payload": data, "commit": True,
        })
    raise ValueError("Unrecognized write action")


async def confirm_change(approval_id: str, choice: Literal["CONFIRM", "CANCEL"]) -> dict[str, Any]:
    """App-visible only. Never register as model-visible tool."""
    _db_ready()
    with connection() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute(
                "select * from sppg_mcp_approvals where id=%s and operator_sub=%s for update",
                (approval_id, OWNER),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Approval request not found")
            if row['status'] in {'PENDING', 'DRAFT'}:
                _confirmation_outcome(cur, approval_id, 'RECEIVED')
            if choice == "CANCEL" and row["status"] == "DRAFT":
                cur.execute("update sppg_mcp_approvals set status='DECLINED',confirmed_at=now() where id=%s", (approval_id,))
                conn.commit()
                return {"approvalId": approval_id,"status":"DECLINED","committed":False}
            if row["status"] != "PENDING":
                conn.commit()
                return {
                    "approvalId": approval_id, "status": row["status"],
                    "result": row.get("result_data"), "message": "Already decided; will not execute twice.",
                }
            if choice == "CANCEL":
                cur.execute(
                    "update sppg_mcp_approvals set status='DECLINED',confirmed_at=now() where id=%s",
                    (approval_id,),
                )
                conn.commit()
                return {"approvalId": approval_id, "status": "DECLINED", "committed": False}
            if not operational_writes_enabled():
                _confirmation_outcome(cur, approval_id, 'WRITE_GATE_CLOSED')
                conn.commit()
                return {
                    "approvalId": approval_id, "status": "WRITE_GATE_CLOSED",
                    "committed": False,
                    "message": "Production write gate has not been enabled.",
                }
            if row["expires_at"] < datetime.now(timezone.utc):
                _confirmation_outcome(cur, approval_id, 'EXPIRED')
                cur.execute(
                    "update sppg_mcp_approvals set status='EXPIRED' where id=%s", (approval_id,)
                )
                conn.commit()
                return {"approvalId": approval_id, "status": "EXPIRED", "committed": False}
            conn.commit()

    change = ChangeRequest(
        action=row["action"], payload=row["proposed_payload"],
        site=row["site"], reason=row["reason"],
    )
    # Revalidate against current live state, not only old preview text.
    try:
        fresh_preview, current, impact = await _preview(change)
        if fresh_preview.get("canCommit") is False:
            _save_confirmation_outcome(approval_id, 'REVALIDATION_FAILED', 'Current preview requires unresolved input')
            return {"approvalId":approval_id,"status":"REVALIDATION_FAILED","committed":False,"reason":"Current preview requires unresolved input"}
        if row["before_hash"] and _hash_json(current) != row["before_hash"]:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "update sppg_mcp_approvals set status='STALE',error_message=%s where id=%s and status='PENDING'",
                        ("Live record changed since preview; prepare a fresh card.", approval_id),
                    )
                    conn.commit()
            return {"approvalId": approval_id, "status": "STALE", "committed": False}
        if _hash_json(fresh_preview) != _hash_json(row["preview_data"]):
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "update sppg_mcp_approvals set status='STALE',error_message=%s where id=%s and status='PENDING'",
                        ("Preview changed since the card was prepared.", approval_id),
                    )
                    conn.commit()
            return {"approvalId": approval_id, "status": "STALE", "committed": False}
    except Exception as exc:
        _save_confirmation_outcome(approval_id, 'REVALIDATION_FAILED', str(exc))
        return {"approvalId": approval_id, "status": "REVALIDATION_FAILED", "committed": False,
                "reason": str(exc)[:600]}

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update sppg_mcp_approvals
                   set status='EXECUTING',confirmed_at=now()
                   where id=%s and operator_sub=%s and status='PENDING' and expires_at>now()
                   returning id""",
                (approval_id, OWNER),
            )
            claimed = cur.fetchone()
            conn.commit()
            if not claimed:
                return {"approvalId": approval_id, "status": "NOT_CLAIMED", "committed": False}

    try:
        result = await _execute(change)
        state = "APPLIED" if result.get("committed", True) else "FAILED_NEEDS_REVIEW"
        error_message = None
    except Exception as exc:
        result = {"detail": "Execution failed. Verify current records before creating a new approval."}
        state = "FAILED_NEEDS_REVIEW"
        error_message = str(exc)[:1200]

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update sppg_mcp_approvals
                   set status=%s,executed_at=now(),result_data=%s::jsonb,error_message=%s
                   where id=%s and operator_sub=%s and status='EXECUTING'""",
                (state, json.dumps(result, default=str, ensure_ascii=False), error_message, approval_id, OWNER),
            )
            _confirmation_outcome(cur, approval_id, state, error_message)
            conn.commit()
    return {
        "approvalId": approval_id, "status": state,
        "committed": bool(state == "APPLIED"),
        "result": result,
        "message": (
            "Operation executed once and audit result stored."
            if state == "APPLIED" else
            "Execution uncertain/failed. Do not retry automatically; inspect current state."
        ),
    }



async def amend_change(approval_id: str, edits: dict[str, Any]) -> dict[str, Any]:
    """Claim the old ticket before creating a reviewed replacement; never commits domain data."""
    _db_ready()
    with connection() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute("select * from sppg_mcp_approvals where id=%s and operator_sub=%s for update", (approval_id,OWNER))
            row=cur.fetchone()
            if not row or row['status'] not in {'PENDING','DRAFT'}:
                raise ValueError('Proposal tidak dapat diedit; muat status terbaru')
            if row['expires_at'] < datetime.now(timezone.utc):
                raise ValueError('Proposal kedaluwarsa; buat preview baru')
            data=apply_form(row['action'],row['proposed_payload'],row['preview_data'],edits)
            cur.execute("update sppg_mcp_approvals set status='SUPERSEDED',confirmed_at=now() where id=%s",(approval_id,))
            conn.commit()
    return await prepare_change(row['action'],data,row['site'],row['reason'])


