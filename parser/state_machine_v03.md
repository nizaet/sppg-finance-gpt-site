# WhatsApp Event State Machine v0.3

## PO lifecycle
DRAFT -> SENT -> ACKNOWLEDGED -> REVISED* -> RECEIVED -> RECONCILED -> CLOSED

Rules:
- `REVISED` may occur multiple times.
- A revision never overwrites the prior version; store revision sequence/version.
- If no active PO can be resolved confidently, store the chat event as an unmatched candidate.

## Payment lifecycle
PAYMENT_NOT_DUE -> PAYMENT_DUE -> PAYMENT_REQUESTED -> PAYMENT_INTENT -> PAYMENT_EVIDENCE_RECEIVED -> PAID

Critical rule:
- `nanti saya transfer`, `saya transfer ya`, or similar future/intention language = PAYMENT_INTENT, not PAID.
- PAID requires completed-payment evidence or explicit operator confirmation.

## Delivery lifecycle
SCHEDULED -> IN_TRANSIT -> RECEIVED -> RECEIPT_ADJUSTED -> QUALITY_RECONCILED

Keep distinct:
- ordered_qty
- dispatched_qty when known
- received_qty
- rejected_qty
- accepted_qty

## Koperasi transfer lifecycle
TRANSFER_REQUESTED -> PICKED_FROM_KOPERASI -> IN_TRANSIT -> RECEIVED_AT_KITCHEN

No purchase expense is created at kitchen receipt when goods came from internal Koperasi inventory.

## Internal cash procurement lifecycle
PURCHASE_REQUESTED -> PURCHASED_WITH_CASH -> INTERNAL_REIMBURSEMENT_PENDING -> INTERNAL_REIMBURSED

Use for known Mungki-mediated cash flows only when the item/site context matches configured master rules.

## Ambiguity policy
When actor, site, production cycle, PO, or payment reference is ambiguous:
1. retain raw message reference;
2. create candidate event;
3. attach possible matches with confidence;
4. do not mutate financial ledger;
5. resolve later from subsequent chat, document evidence, or operator input.
