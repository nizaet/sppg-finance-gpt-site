from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.gpt_bridge_api import require_gpt_auth

router = APIRouter(prefix="/gpt", tags=["gpt-knowledge-runtime"])
RULES_PATH = Path(__file__).resolve().parent / "knowledge" / "runtime_rules_v1.json"
JAKARTA = ZoneInfo("Asia/Jakarta")


def _rules() -> dict[str, Any]:
    try:
        value = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"version": "unavailable", "loadError": f"{type(exc).__name__}: {exc}"[:1000], "decisionPolicy": [], "canonicalFacts": {}}


def _safe_query(sql: str, params: list[Any] | tuple[Any, ...]) -> dict[str, Any]:
    if not database_ready():
        return {"items": [], "error": "database unavailable"}
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return {"items": [dict(row) for row in cur.fetchall()], "error": None}
    except Exception as exc:
        return {"items": [], "error": f"{type(exc).__name__}: {exc}"[:1500]}


def _vendor_rules(site: str | None, vendor: str | None, as_of: date, limit: int) -> dict[str, Any]:
    sql = """
        select vr.id,vr.vendor_code,e.name as vendor_name,vr.site_code,vr.category_code,
               vr.lead_time_days_before_cooking,vr.payment_term_code,vr.payment_term_payload,
               vr.internal_reimbursement,vr.intermediary_code,vr.effective_from,vr.effective_to,vr.evidence_ref,vr.notes
        from vendor_rules vr left join entities e on e.code=vr.vendor_code
        where vr.effective_from<=%s and (vr.effective_to is null or vr.effective_to>=%s)
    """
    params: list[Any] = [as_of, as_of]
    if site:
        sql += " and (vr.site_code is null or upper(vr.site_code)=upper(%s))"
        params.append(site)
    if vendor:
        sql += " and upper(vr.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by vr.vendor_code,vr.site_code nulls first,vr.category_code nulls first,vr.effective_from desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _open_pos(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select po.id as purchase_order_id,po.po_code,po.revision_no,po.site,po.vendor_code,po.status,
               po.sent_at,po.created_at,pc.distribution_date,pc.cooking_at,
               poi.id as purchase_order_item_id,poi.item_code,poi.item_name,poi.po_qty,poi.unit,
               coalesce((select sum(coalesce(gri.accepted_qty,gri.received_qty,0))
                         from goods_receipt_items gri where gri.purchase_order_item_id=poi.id),0) as received_qty,
               greatest(coalesce(poi.po_qty,0)-coalesce((select sum(coalesce(gri2.accepted_qty,gri2.received_qty,0))
                         from goods_receipt_items gri2 where gri2.purchase_order_item_id=poi.id),0),0) as outstanding_qty
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        join purchase_order_items poi on poi.purchase_order_id=po.id
        where upper(po.status) in ('DRAFT','FINALIZED','SENT','ACKNOWLEDGED','PARTIAL_RECEIVED')
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by pc.distribution_date desc nulls last,po.created_at desc,po.id desc,poi.id limit %s"
    params.append(max(limit * 20, limit))
    raw = _safe_query(sql, params)
    if raw.get("error"):
        return raw
    grouped: dict[int, dict[str, Any]] = {}
    for row in raw["items"]:
        po_id = int(row["purchase_order_id"])
        po = grouped.setdefault(po_id, {
            "purchaseOrderId": po_id, "poCode": row.get("po_code"), "revisionNo": row.get("revision_no"),
            "site": row.get("site"), "vendorCode": row.get("vendor_code"), "status": row.get("status"),
            "distributionDate": row.get("distribution_date"), "cookingAt": row.get("cooking_at"),
            "sentAt": row.get("sent_at"), "createdAt": row.get("created_at"), "items": [],
        })
        po["items"].append({
            "purchaseOrderItemId": row.get("purchase_order_item_id"), "itemCode": row.get("item_code"),
            "itemName": row.get("item_name"), "poQty": row.get("po_qty"), "receivedQty": row.get("received_qty"),
            "outstandingQty": row.get("outstanding_qty"), "unit": row.get("unit"),
        })
    return {"items": list(grouped.values())[:limit], "error": None}


def _recent_receipts(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select gr.id as goods_receipt_id,gr.purchase_order_id,gr.received_at,gr.reporter,gr.match_status,gr.match_confidence,
               po.po_code,po.site,po.vendor_code,pc.distribution_date,count(gri.id) as item_count,
               coalesce(sum(coalesce(gri.accepted_qty,gri.received_qty,0)),0) as accepted_qty_total
        from goods_receipts gr join purchase_orders po on po.id=gr.purchase_order_id
        left join production_cycles pc on pc.id=po.production_cycle_id
        left join goods_receipt_items gri on gri.goods_receipt_id=gr.id where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " group by gr.id,po.id,pc.id order by gr.received_at desc nulls last,gr.id desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _payables(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select vi.id as vendor_invoice_id,vi.vendor_code,vi.site,vi.purchase_order_id,vi.goods_receipt_id,
               vi.invoice_number,vi.invoice_date,vi.net_amount,vi.payable_status,vi.due_date,vi.created_at,po.po_code
        from vendor_invoices vi left join purchase_orders po on po.id=vi.purchase_order_id
        where upper(coalesce(vi.payable_status,'UNPAID')) not in ('PAID','SETTLED')
    """
    params: list[Any] = []
    if site:
        sql += " and upper(vi.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(vi.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by vi.created_at desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _payments(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select vp.id as vendor_payment_id,vp.vendor_invoice_id,vp.vendor_code,vp.site,vp.amount,vp.payment_status,
               vp.payment_source,vp.paid_at,vp.evidence_uri,vp.reference_number,vp.candidate_purchase_order_id,
               vp.candidate_goods_receipt_id,vp.candidate_vendor_invoice_id,vp.reconciliation_note,vp.reconciled_at,vp.created_at
        from vendor_payments vp where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(vp.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(vp.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by vp.paid_at desc nulls last,vp.id desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _reviews(site: str | None, vendor: str | None, limit: int) -> dict[str, Any]:
    sql = """
        select id,event_type,site,vendor_code,event_time,confidence,requires_confirmation,status,created_at
        from candidate_events where upper(status) in ('PENDING','PENDING_REVIEW','REVIEW')
    """
    params: list[Any] = []
    if site:
        sql += " and (site is null or upper(site)=upper(%s))"
        params.append(site)
    if vendor:
        sql += " and (vendor_code is null or upper(vendor_code)=upper(%s))"
        params.append(vendor)
    sql += " order by created_at desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _learned_knowledge(site: str | None, vendor: str | None, query: str, limit: int) -> dict[str, Any]:
    sql = """
        select id,scope_type,site,vendor_code,topic,statement,knowledge_kind,status,confidence,
               evidence_count,metadata,last_seen_at
        from llm_learned_knowledge
        where status='CONFIRMED'
    """
    params: list[Any] = []
    if site:
        sql += " and (site is null or upper(site)=upper(%s))"
        params.append(site)
    if vendor:
        sql += " and (vendor_code is null or upper(vendor_code)=upper(%s))"
        params.append(vendor)
    if query.strip():
        sql += " and to_tsvector('simple',coalesce(topic,'') || ' ' || coalesce(statement,'')) @@ plainto_tsquery('simple',%s)"
        params.append(query.strip())
    sql += " order by confidence desc,evidence_count desc,last_seen_at desc limit %s"
    params.append(limit)
    return _safe_query(sql, params)


def _conversation_memory(site: str | None, vendor: str | None, query: str, limit: int) -> dict[str, Any]:
    sql = """
        select id,conversation_ref,turn_ref,site,vendor_code,
               left(user_message,1800) as user_message,left(coalesce(assistant_summary,''),1800) as assistant_summary,
               action_context,created_at
        from llm_conversation_events where true
    """
    params: list[Any] = []
    if site:
        sql += " and (site is null or upper(site)=upper(%s))"
        params.append(site)
    if vendor:
        sql += " and (vendor_code is null or upper(vendor_code)=upper(%s))"
        params.append(vendor)
    if query.strip():
        sql += " and to_tsvector('simple',coalesce(user_message,'') || ' ' || coalesce(assistant_summary,'')) @@ plainto_tsquery('simple',%s)"
        params.append(query.strip())
    sql += " order by created_at desc limit %s"
    params.append(min(limit, 12))
    return _safe_query(sql, params)


def _normalize_statement(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip().lower())
    return re.sub(r"[^a-z0-9\s:/+.,=%-]+", "", text)


def _knowledge_status(kind: str, confidence: float) -> str:
    if kind in {"USER_CORRECTION", "ACTION_CONFIRMED"} and confidence >= 0.80:
        return "CONFIRMED"
    if kind == "USER_EXPLICIT" and confidence >= 0.95:
        return "CONFIRMED"
    return "CANDIDATE"


class LearnedFactIn(BaseModel):
    statement: str = Field(min_length=3, max_length=1500)
    kind: Literal["USER_EXPLICIT", "USER_CORRECTION", "ACTION_CONFIRMED", "ASSISTANT_INFERENCE"]
    scope_type: Literal["GLOBAL", "SITE", "VENDOR", "ITEM", "WORKFLOW"] = "GLOBAL"
    topic: str | None = Field(default=None, max_length=160)
    confidence: float = Field(default=1.0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationLearnIn(BaseModel):
    conversation_ref: str = Field(min_length=1, max_length=200)
    turn_ref: str | None = Field(default=None, max_length=200)
    site: Literal["MAJA", "CEMPLANG"] | None = None
    vendor: str | None = Field(default=None, max_length=100)
    user_message: str = Field(min_length=1, max_length=20000)
    assistant_summary: str | None = Field(default=None, max_length=6000)
    action_context: dict[str, Any] = Field(default_factory=dict)
    facts: list[LearnedFactIn] = Field(default_factory=list, max_length=30)
    actor: str = Field(default="chatgpt", max_length=100)


class ExplicitKnowledgeFactIn(BaseModel):
    statement: str = Field(min_length=3, max_length=1500)
    scope_type: Literal["GLOBAL", "SITE", "VENDOR", "ITEM", "WORKFLOW"] = "GLOBAL"
    topic: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExplicitKnowledgeIn(BaseModel):
    source_ref: str = Field(min_length=1, max_length=200)
    site: Literal["MAJA", "CEMPLANG"] | None = None
    vendor: str | None = Field(default=None, max_length=100)
    user_message: str = Field(min_length=1, max_length=20000)
    facts: list[ExplicitKnowledgeFactIn] = Field(min_length=1, max_length=30)
    actor: str = Field(default="chatgpt", max_length=100)


@router.post("/learn-conversation", dependencies=[Depends(require_gpt_auth)])
def learn_conversation(payload: ConversationLearnIn) -> dict[str, Any]:
    """Archive a GPT turn and promote only explicit/corrected/confirmed durable facts."""
    if not database_ready():
        return {"stored": False, "databaseReady": False, "error": "database unavailable", "promoted": [], "candidates": []}

    vendor_code = (payload.vendor or "").upper().strip() or None
    identity = {
        "conversation": payload.conversation_ref,
        "turn": payload.turn_ref,
        "site": payload.site,
        "vendor": vendor_code,
        "message": payload.user_message,
    }
    source_key = "gpt-conversation:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    promoted: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into llm_conversation_events(
                  source_key,conversation_ref,turn_ref,site,vendor_code,user_message,assistant_summary,action_context,actor
                ) values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                on conflict (source_key) do update set
                  assistant_summary=coalesce(excluded.assistant_summary,llm_conversation_events.assistant_summary),
                  action_context=case when excluded.action_context='{}'::jsonb then llm_conversation_events.action_context else excluded.action_context end
                returning id
                """,
                (
                    source_key, payload.conversation_ref, payload.turn_ref, payload.site, vendor_code,
                    payload.user_message, payload.assistant_summary,
                    json.dumps(payload.action_context, ensure_ascii=False), payload.actor,
                ),
            )
            event_id = int(cur.fetchone()["id"])

            for fact in payload.facts:
                normalized = _normalize_statement(fact.statement)
                if not normalized:
                    continue
                status = _knowledge_status(fact.kind, fact.confidence)
                scope_site = payload.site if fact.scope_type in {"SITE", "ITEM", "WORKFLOW"} else None
                scope_vendor = vendor_code if fact.scope_type in {"VENDOR", "ITEM", "WORKFLOW"} else None
                key_seed = "|".join([
                    fact.scope_type, scope_site or "", scope_vendor or "", (fact.topic or "").strip().lower(), normalized,
                ])
                knowledge_key = "learned:" + hashlib.sha256(key_seed.encode("utf-8")).hexdigest()
                cur.execute(
                    """
                    insert into llm_learned_knowledge(
                      knowledge_key,scope_type,site,vendor_code,topic,statement,normalized_statement,
                      knowledge_kind,status,confidence,evidence_event_id,metadata
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    on conflict (knowledge_key) do update set
                      statement=excluded.statement,
                      knowledge_kind=case
                        when llm_learned_knowledge.knowledge_kind='ACTION_CONFIRMED' then llm_learned_knowledge.knowledge_kind
                        when excluded.knowledge_kind in ('ACTION_CONFIRMED','USER_CORRECTION') then excluded.knowledge_kind
                        else llm_learned_knowledge.knowledge_kind end,
                      status=case
                        when llm_learned_knowledge.status='REJECTED' then llm_learned_knowledge.status
                        when excluded.status='CONFIRMED' then 'CONFIRMED'
                        else llm_learned_knowledge.status end,
                      confidence=greatest(llm_learned_knowledge.confidence,excluded.confidence),
                      evidence_event_id=excluded.evidence_event_id,
                      evidence_count=llm_learned_knowledge.evidence_count+1,
                      metadata=llm_learned_knowledge.metadata || excluded.metadata,
                      last_seen_at=now(),updated_at=now()
                    returning id,status,confidence,evidence_count
                    """,
                    (
                        knowledge_key, fact.scope_type, scope_site, scope_vendor, fact.topic, fact.statement.strip(), normalized,
                        fact.kind, status, fact.confidence, event_id, json.dumps(fact.metadata, ensure_ascii=False),
                    ),
                )
                row = dict(cur.fetchone())
                item = {"knowledgeId": row["id"], "statement": fact.statement.strip(), "status": row["status"],
                        "confidence": float(row["confidence"]), "evidenceCount": row["evidence_count"]}
                (promoted if row["status"] == "CONFIRMED" else candidates).append(item)
            conn.commit()

    return {
        "stored": True,
        "databaseReady": True,
        "eventId": event_id,
        "sourceKey": source_key,
        "promoted": promoted,
        "candidates": candidates,
        "policy": "Every turn is archived. Only explicit user facts, user corrections, and action-confirmed facts become trusted knowledge; assistant inference stays candidate.",
    }


@router.post("/knowledge", dependencies=[Depends(require_gpt_auth)])
def record_explicit_knowledge(payload: ExplicitKnowledgeIn) -> dict[str, Any]:
    """Confirm facts that the operator explicitly asks to store as LLM Wiki knowledge.

    This memory-only route deliberately bypasses the operational candidate-event
    parser. It never mutates PO, inventory, receiving, payment, or finance state.
    """
    result = learn_conversation(ConversationLearnIn(
        conversation_ref=f"explicit-knowledge:{payload.source_ref}",
        turn_ref=payload.source_ref,
        site=payload.site,
        vendor=payload.vendor,
        user_message=payload.user_message,
        assistant_summary="Explicit operator instruction to store durable SPPG knowledge.",
        action_context={"sourceRef": payload.source_ref, "knowledgeWrite": True},
        facts=[
            LearnedFactIn(
                statement=fact.statement,
                kind="USER_EXPLICIT",
                scope_type=fact.scope_type,
                topic=fact.topic,
                confidence=1.0,
                metadata={**fact.metadata, "sourceRef": payload.source_ref, "explicitlyRequested": True},
            )
            for fact in payload.facts
        ],
        actor=payload.actor,
    ))
    result.update({
        "knowledgeWrite": True,
        "knowledgeStatus": "CONFIRMED" if result.get("stored") and not result.get("candidates") else "FAILED",
        "operationalMutation": False,
    })
    return result


@router.get("/operational-context", dependencies=[Depends(require_gpt_auth)])
def operational_context(
    site: Literal["MAJA", "CEMPLANG"] | None = None,
    vendor: str = "",
    q: str = Query(default="", max_length=500),
    as_of: date | None = Query(default=None, alias="asOf"),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Return durable rules, learned conversation knowledge, and current PostgreSQL facts."""
    vendor_code = vendor.upper().strip() or None
    effective_date = as_of or datetime.now(JAKARTA).date()
    sections = {
        "learnedKnowledge": _learned_knowledge(site, vendor_code, q, limit),
        "conversationMemory": _conversation_memory(site, vendor_code, q, limit),
        "vendorRules": _vendor_rules(site, vendor_code, effective_date, limit),
        "openPurchaseOrders": _open_pos(site, vendor_code, limit),
        "recentGoodsReceipts": _recent_receipts(site, vendor_code, limit),
        "openPayables": _payables(site, vendor_code, limit),
        "recentPayments": _payments(site, vendor_code, limit),
        "reviewQueue": _reviews(site, vendor_code, limit),
    }
    errors = {name: value.get("error") for name, value in sections.items() if value.get("error")}
    return {
        "runtimeVersion": "llm-knowledge-runtime-v2",
        "generatedAt": datetime.now(JAKARTA).isoformat(),
        "asOf": effective_date.isoformat(),
        "query": q or None,
        "databaseReady": database_ready(),
        "site": site,
        "vendorCode": vendor_code,
        "sourceOfTruth": "PostgreSQL for live state and learned conversation memory; canonical runtime rules for durable policy; Drive for evidence/archive.",
        "canonicalKnowledge": _rules(),
        "liveContext": {name: value.get("items", []) for name, value in sections.items()},
        "sectionErrors": errors,
        "safeToUseForWrites": bool(database_ready() and not errors.get("openPurchaseOrders")),
    }
