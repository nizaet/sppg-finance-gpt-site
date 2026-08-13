# Event Ingestion Contract v0.4

## Goal
Convert chat/source evidence into append-only candidate events before any transactional mutation.

## Input
- source_type: WHATSAPP | APP_CHAT | DRIVE_FILE | MANUAL
- source_message_id / file_id
- occurred_at
- actor_entity_id
- counterparty_entity_id
- raw_text
- evidence_url

## Parser output
Every parser result must include:
- event_id
- event_type
- confidence
- requires_confirmation
- raw_text
- site
- vendor/entity references when inferred
- structured_payload
- source provenance

## Safety gates
1. PAYMENT_INTENT never changes payment status.
2. PAYMENT_EVIDENCE_CANDIDATE never becomes PAID without amount/account reconciliation or explicit operator confirmation.
3. PO_NEW_CANDIDATE does not become SENT until the outgoing message/evidence is linked.
4. PO_REVISION creates a new revision/event and never overwrites the historical PO snapshot.
5. GOODS_RECEIVED_CANDIDATE must reconcile ordered/received/rejected quantities before closing procurement.
6. KOPERASI_STOCK_TRANSFER_REQUEST creates stock movement only, not a new kitchen purchase expense.
7. Ambiguous site/vendor/entity matches remain candidates.

## Database boundary
Parser writes first to `workflow_events` / `whatsapp_events` staging.
A workflow service then validates and mutates domain tables such as:
- purchase_orders
- po_items
- goods_receipts
- vendor_invoices
- vendor_payments
- stock_movements
- internal_reimbursements

The parser must not directly mutate financial balances.

## Idempotency
Use a stable source key such as:
`source_type + source_message_id + event_type`
to prevent duplicate ingestion when the same chat export/webhook is processed more than once.

## Provenance
All durable events must retain source evidence reference. Raw source is immutable.
