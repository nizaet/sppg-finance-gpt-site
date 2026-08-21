from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from backend.db import database_ready
from backend.gpt_bridge_api import require_gpt_auth
from backend.knowledge_runtime_api import (
    _learned_knowledge,
    _open_pos,
    _payments,
    _payables,
    _recent_receipts,
    _rules,
    _vendor_rules,
)

router = APIRouter(prefix="/v1/llm-wiki", tags=["hermes-llm-wiki-readonly"])
JAKARTA = ZoneInfo("Asia/Jakarta")

Topic = Literal[
    "all",
    "knowledge",
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


@router.get("/context", dependencies=[Depends(require_gpt_auth)])
def llm_wiki_context(
    site: Literal["MAJA", "CEMPLANG"] | None = None,
    vendor: str = Query(default="", max_length=100),
    topic: Topic = "all",
    q: str = Query(default="", max_length=500),
    as_of: date | None = Query(default=None, alias="asOf"),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Read-only operational knowledge context for Hermes.

    PostgreSQL remains the source of truth for live operational state. Canonical
    runtime rules and confirmed learned knowledge provide durable context.
    Drive is referenced only through stored evidence/archive URIs; this endpoint
    never reads or writes Drive directly and performs no database mutations.
    """
    vendor_code = vendor.upper().strip() or None
    effective_date = as_of or datetime.now(JAKARTA).date()

    vendor_rules = _vendor_rules(site, vendor_code, effective_date, limit)
    learned_knowledge = _learned_knowledge(site, vendor_code, q, limit)
    open_pos = _open_pos(site, vendor_code, limit)
    recent_receipts = _recent_receipts(site, vendor_code, limit)
    open_payables = _payables(site, vendor_code, limit)
    recent_payments = _payments(site, vendor_code, limit)

    all_sections: dict[str, dict[str, Any]] = {
        "learnedKnowledge": learned_knowledge,
        "vendorRules": vendor_rules,
        "openPurchaseOrders": open_pos,
        "recentGoodsReceipts": recent_receipts,
        "openPayables": open_payables,
        "recentPayments": recent_payments,
    }

    topic_sections: dict[str, tuple[str, ...]] = {
        "all": tuple(all_sections.keys()),
        "knowledge": ("learnedKnowledge", "vendorRules"),
        "procurement": ("vendorRules", "openPurchaseOrders", "recentGoodsReceipts"),
        "po": ("vendorRules", "openPurchaseOrders", "recentGoodsReceipts"),
        "receiving": ("vendorRules", "openPurchaseOrders", "recentGoodsReceipts"),
        "payment": ("vendorRules", "openPayables", "recentPayments"),
        "payments": ("vendorRules", "openPayables", "recentPayments"),
    }
    selected_names = topic_sections[topic]
    selected = {name: all_sections[name] for name in selected_names}
    errors = {name: value.get("error") for name, value in selected.items() if value.get("error")}

    return {
        "runtimeVersion": "hermes-llm-wiki-context-v1",
        "generatedAt": datetime.now(JAKARTA).isoformat(),
        "asOf": effective_date.isoformat(),
        "accessMode": "READ_ONLY",
        "writesExposed": False,
        "databaseReady": database_ready(),
        "site": site,
        "vendorCode": vendor_code,
        "topic": topic,
        "query": q or None,
        "sourceOfTruth": {
            "liveState": "PostgreSQL",
            "durableRules": "canonical runtime rules + confirmed learned knowledge",
            "drive": "evidence/archive references only; no direct Drive access",
        },
        "canonicalKnowledge": _rules(),
        "context": {name: _items(value) for name, value in selected.items()},
        "evidenceReferences": _evidence_references(vendor_rules, recent_payments, learned_knowledge),
        "sectionErrors": errors,
    }
