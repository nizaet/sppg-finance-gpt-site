from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping


class Decision(str, Enum):
    AUTO_ACCEPT = "AUTO_ACCEPT"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"
    REJECT = "REJECT"


@dataclass(frozen=True)
class CandidateEvent:
    event_type: str
    source_type: str
    source_id: str
    source_message_id: str | None
    site: str | None
    actor: str | None
    vendor: str | None
    confidence: float
    requires_confirmation: bool
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def idempotency_key(self) -> str:
        raw = "|".join([
            self.source_type or "",
            self.source_id or "",
            self.source_message_id or "",
            self.event_type or "",
            self.site or "",
            self.vendor or "",
        ])
        return sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ValidationResult:
    decision: Decision
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainCommand:
    command_type: str
    aggregate_type: str
    payload: Mapping[str, Any]


HIGH_RISK_EVENTS = {
    "PAYMENT_EVIDENCE_CANDIDATE",
    "PAYMENT_CONFIRMED",
    "APPROVAL_CONFIRMED",
    "BGN_FUNDS_RECEIVED",
    "SETTLEMENT_TO_OPERATIONAL",
}

SAFE_AUTOMATION_EVENTS = {
    "PO_ACKNOWLEDGED",
    "GOODS_IN_TRANSIT",
    "DELIVERY_SCHEDULE_CONFIRMED",
    "QUALITY_REJECT_REPORTED",
    "KOPERASI_STOCK_TRANSFER_REQUEST",
}


def validate_candidate(event: CandidateEvent) -> ValidationResult:
    reasons: list[str] = []

    if not event.source_id:
        return ValidationResult(Decision.REJECT, ("missing_source_id",))

    if not (0 <= event.confidence <= 1):
        return ValidationResult(Decision.REJECT, ("invalid_confidence",))

    if event.event_type in HIGH_RISK_EVENTS:
        reasons.append("high_risk_event_requires_review")
        return ValidationResult(Decision.REQUIRE_REVIEW, tuple(reasons))

    if event.requires_confirmation:
        reasons.append("parser_requested_confirmation")
        return ValidationResult(Decision.REQUIRE_REVIEW, tuple(reasons))

    if event.confidence < 0.90:
        reasons.append("confidence_below_auto_accept_threshold")
        return ValidationResult(Decision.REQUIRE_REVIEW, tuple(reasons))

    if event.event_type in SAFE_AUTOMATION_EVENTS:
        return ValidationResult(Decision.AUTO_ACCEPT)

    reasons.append("event_not_in_safe_automation_set")
    return ValidationResult(Decision.REQUIRE_REVIEW, tuple(reasons))


def build_domain_command(event: CandidateEvent) -> DomainCommand | None:
    mapping = {
        "PO_NEW": ("CREATE_PURCHASE_ORDER", "purchase_order"),
        "PO_REVISION": ("CREATE_PO_REVISION", "purchase_order"),
        "PO_ACKNOWLEDGED": ("ACKNOWLEDGE_PURCHASE_ORDER", "purchase_order"),
        "GOODS_RECEIVED": ("RECORD_GOODS_RECEIPT", "goods_receipt"),
        "QUALITY_REJECT_REPORTED": ("RECORD_REJECT", "goods_receipt"),
        "VENDOR_INVOICE": ("RECORD_VENDOR_INVOICE", "vendor_invoice"),
        "PAYMENT_EVIDENCE_CANDIDATE": ("RECORD_PAYMENT_EVIDENCE", "vendor_payment"),
        "KOPERASI_STOCK_TRANSFER_REQUEST": ("CREATE_STOCK_TRANSFER", "stock_movement"),
        "ACTUAL_USAGE_FINALIZED": ("FINALIZE_ACTUAL_USAGE", "actual_usage"),
        "ACCOUNTANT_EXCEL_SENT": ("RECORD_ACCOUNTANT_SUBMISSION", "accountant_submission"),
        "ACCOUNTANT_INVOICE_RECEIVED": ("RECORD_ACCOUNTANT_INVOICE", "accountant_invoice"),
        "BGN_MAKER_CREATED": ("CREATE_BGN_MAKER", "bgn_maker"),
        "APPROVAL_CONFIRMED": ("CONFIRM_BGN_APPROVAL", "bgn_approval"),
        "BGN_FUNDS_RECEIVED": ("RECORD_BGN_RECEIPT", "bgn_receipt"),
        "SETTLEMENT_TO_OPERATIONAL": ("RECORD_SETTLEMENT", "settlement"),
    }
    found = mapping.get(event.event_type)
    if not found:
        return None
    command_type, aggregate_type = found
    payload = dict(event.payload)
    payload.update({
        "site": event.site,
        "actor": event.actor,
        "vendor": event.vendor,
        "source_id": event.source_id,
        "source_message_id": event.source_message_id,
        "idempotency_key": event.idempotency_key,
    })
    return DomainCommand(command_type, aggregate_type, payload)
