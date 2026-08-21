from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from backend.db import database_ready
from backend.gpt_bridge_api import require_gpt_auth
from backend.knowledge_runtime_api import (
    ConversationLearnIn,
    _conversation_memory,
    _learned_knowledge,
    _open_pos,
    _payments,
    _payables,
    _recent_receipts,
    _rules,
    _vendor_rules,
    learn_conversation,
)

router = APIRouter(prefix="/v1/llm-wiki", tags=["hermes-llm-wiki"])
JAKARTA = ZoneInfo("Asia/Jakarta")

Topic = Literal[
    "all",
    "knowledge",
    "behavior",
    "procurement",
    "po",
    "receiving",
    "payment",
    "payments",
]


def _items(section: dict[str, Any]) -> list[dict[str, Any]]:
    value = section.get("items", [])
    return value if isinstance(value, list) else []


def _evidence_references(
    vendor_rules: dict[str, Any],
    payments: dict[str, Any],
    learned_knowledge: dict[str, Any],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for rule in _items(vendor_rules):
        ref = rule.get("evidence_ref")
        if ref and str(ref) not in seen:
            seen.add(str(ref))
            refs.append({"source": "vendor_rule", "reference": ref})

    for payment in _items(payments):
        ref = payment.get("evidence_uri")
        if ref and str(ref) not in seen:
            seen.add(str(ref))
            refs.append({"source": "vendor_payment", "reference": ref})

    for fact in _items(learned_knowledge):
        metadata = fact.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("evidenceRef", "evidence_ref", "driveUri", "drive_uri", "sourceUri", "source_uri"):
            ref = metadata.get(key)
            if ref and str(ref) not in seen:
                seen.add(str(ref))
                refs.append({"source": "learned_knowledge", "reference": ref})

    return refs[:100]


@router.post("/learn-conversation", dependencies=[Depends(require_gpt_auth)])
def hermes_learn_conversation(payload: ConversationLearnIn) -> dict[str, Any]:
    """Store Hermes turns in the same durable memory used by the legacy GPTS.

    This endpoint is intentionally memory-only. It does not create or mutate PO,
    goods receipt, payment, inventory, finance, or other operational records.
    """
    if not payload.actor or payload.actor == "chatgpt":
        payload.actor = "hermes"
    result = learn_conversation(payload)
    result["memoryScope"] = "shared-gpts-hermes"
    result["operationalMutation"] = False
    return result


@router.get("/context", dependencies=[Depends(require_gpt_auth)])
def llm_wiki_context(
    site: Literal["MAJA", "CEMPLANG"] | None = None,
    vendor: str = Query(default="", max_length=100),
    topic: Topic = "all",
    q: str = Query(default="", max_length=500),
    as_of: date | None = Query(default=None, alias="asOf"),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Operational and behavioral context for Hermes.

    PostgreSQL remains the source of truth for live operational state. Hermes
    reads both confirmed learned knowledge and the conversation history produced
    by the legacy GPTS, so user corrections, approvals, preferred classifications,
    formatting decisions, and workflow habits can carry forward during migration.
    Drive is referenced only through stored evidence/archive URIs.
    """
    vendor_code = vendor.upper().strip() or None
    effective_date = as_of or datetime.now(JAKARTA).date()

    vendor_rules = _vendor_rules(site, vendor_code, effective_date, limit)
    learned_knowledge = _learned_knowledge(site, vendor_code, q, limit)
    conversation_memory = _conversation_memory(site, vendor_code, q, limit)
    open_pos = _open_pos(site, vendor_code, limit)
    recent_receipts = _recent_receipts(site, vendor_code, limit)
    open_payables = _payables(site, vendor_code, limit)
    recent_payments = _payments(site, vendor_code, limit)

    all_sections: dict[str, dict[str, Any]] = {
        "learnedKnowledge": learned_knowledge,
        "conversationMemory": conversation_memory,
        "vendorRules": vendor_rules,
        "openPurchaseOrders": open_pos,
        "recentGoodsReceipts": recent_receipts,
        "openPayables": open_payables,
        "recentPayments": recent_payments,
    }

    topic_sections: dict[str, tuple[str, ...]] = {
        "all": tuple(all_sections.keys()),
        "knowledge": ("learnedKnowledge", "conversationMemory", "vendorRules"),
        "behavior": ("learnedKnowledge", "conversationMemory"),
        "procurement": ("learnedKnowledge", "conversationMemory", "vendorRules", "openPurchaseOrders", "recentGoodsReceipts"),
        "po": ("learnedKnowledge", "conversationMemory", "vendorRules", "openPurchaseOrders", "recentGoodsReceipts"),
        "receiving": ("learnedKnowledge", "conversationMemory", "vendorRules", "openPurchaseOrders", "recentGoodsReceipts"),
        "payment": ("learnedKnowledge", "conversationMemory", "vendorRules", "openPayables", "recentPayments"),
        "payments": ("learnedKnowledge", "conversationMemory", "vendorRules", "openPayables", "recentPayments"),
    }
    selected_names = topic_sections[topic]
    selected = {name: all_sections[name] for name in selected_names}
    errors = {name: value.get("error") for name, value in selected.items() if value.get("error")}

    return {
        "runtimeVersion": "hermes-llm-wiki-context-v2",
        "generatedAt": datetime.now(JAKARTA).isoformat(),
        "asOf": effective_date.isoformat(),
        "accessMode": "READ_CONTEXT_WRITE_MEMORY",
        "writesExposed": True,
        "operationalWritesExposed": False,
        "databaseReady": database_ready(),
        "site": site,
        "vendorCode": vendor_code,
        "topic": topic,
        "query": q or None,
        "sourceOfTruth": {
            "liveState": "PostgreSQL",
            "durableRules": "canonical runtime rules + confirmed learned knowledge",
            "behaviorHistory": "shared llm_conversation_events written by legacy GPTS and Hermes",
            "drive": "evidence/archive references only; no direct Drive access",
        },
        "migrationPolicy": {
            "goal": "allow Hermes to inherit the user's established SPPG operating behavior before replacing the legacy GPTS",
            "readLegacyConversationHistory": True,
            "shareConfirmedKnowledge": True,
            "writeHermesTurnsToSameMemory": True,
            "productionMutationFromLearning": False,
        },
        "canonicalKnowledge": _rules(),
        "context": {name: _items(value) for name, value in selected.items()},
        "evidenceReferences": _evidence_references(vendor_rules, recent_payments, learned_knowledge),
        "sectionErrors": errors,
    }
