# Workflow Service v0.5

## Purpose
Translate validated candidate events into controlled domain actions. Parser output is evidence/candidate data, not a ledger mutation.

## Safety gates
1. Every inbound event gets an `event_key` for idempotency.
2. Duplicate messages or webhook retries must resolve to the same candidate event.
3. Financial finalization requires deterministic evidence or explicit operator validation.
4. State transitions must be monotonic unless a corrective/superseding event is recorded.
5. Historical values are appended/versioned; they are not silently overwritten.
6. Every applied action writes `event_audit_log`.

## Candidate lifecycle
`PENDING -> VALIDATED -> APPLIED`

Alternative outcomes:
- `PENDING -> REJECTED`
- `VALIDATED -> SUPERSEDED`

## Event routing

### PO_NEW
Create a new purchase order draft/version for the relevant site/vendor.

### PO_REVISION
Create a new PO revision linked to the current PO. Preserve earlier quantity and price values.

### PO_ACKNOWLEDGED
Record vendor acknowledgement only. Do not mark goods received.

### GOODS_IN_TRANSIT
Update delivery tracking only.

### GOODS_RECEIVED
Create goods receipt candidate using received quantities. Do not assume ordered quantity equals received quantity.

### QUALITY_REJECT_REPORTED
Create reject record linked to receipt/item. Recalculate accepted quantity only after reconciliation.

### VENDOR_PRICE_CHANGED
Create vendor price observation/effective-price candidate. Never rewrite historical PO/invoice price.

### PAYMENT_INTENT
Create reminder/pending-payment intent only. Never create payment ledger entry.

### PAYMENT_EVIDENCE_CANDIDATE
Queue reconciliation against bank proof, amount, beneficiary, vendor invoice and site before `VENDOR_PAID`.

### KOPERASI_STOCK_TRANSFER_REQUEST
Create internal stock movement request. No purchase expense is created at dispatch time.

### KOPERASI_STOCK_TRANSFER_CONFIRMED
Apply paired inventory movement: decrease Koperasi and increase destination kitchen.

### INTERNAL_CASH_PURCHASE
Create cash-purchase record and reimbursement-pending record when applicable. This is separate from BGN reimbursement.

### ACCOUNTANT_INVOICE_RECEIVED
Link accountant invoice to final costing/production cycle; do not infer BGN approval.

### APPROVAL_LIST_SENT
Create approval request state only.

### APPROVAL_CONFIRMED
Advance maker item only when reference/amount/context resolve to an active pending approval.

## Conflict policy
When two candidate events conflict:
- preserve both raw events;
- mark the newer event as a possible revision, correction, or contradiction;
- never erase prior values;
- require confirmation when deterministic resolution is impossible.

## Idempotency key examples
- WhatsApp message: `wa:{chat_id}:{message_id}`
- Drive import: `drive:{file_id}:{line_or_record_hash}`
- Manual chat input: `chat:{conversation_id}:{turn_id}:{normalized_hash}`

## Application boundary
Only the workflow service may promote a validated candidate event into operational domain tables. Parser code must not have write access to final ledger/payment tables.
