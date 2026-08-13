# BGN Workflow

ACCOUNTANT_INVOICE_RECEIVED -> BGN_MAKER_CREATED -> APPROVAL_LIST_SENT -> APPROVAL_PENDING -> BGN_APPROVED -> BGN_FUNDS_RECEIVED -> SETTLEMENT_TO_OPERATIONAL -> CLOSED.

Approvers:
- Maja -> Embun.
- Cemplang -> Malik.

## Learned approval message pattern
A recurring Cemplang WhatsApp pattern uses `UPDATE PENDING APPROVAL` with:
- date
- transaction label/type
- maker/internal code
- invoice/reference number when available
- counterparty
- amount
- total amount when multiple items are grouped

Rules:
- `APPROVAL_LIST_SENT` does not equal `BGN_APPROVED`.
- Approval status is tracked per maker item, not only per WhatsApp message.
- Later clarification may indicate an item was already approved previously; preserve that evidence and reconcile state instead of creating a duplicate approval.
- Maker deadline requests (for example, historical requests before 08:00) are operational scheduling events, not approval events.

Funds may be received by Yayasan and/or Koperasi before transfer to BCA Operational. That transfer is settlement, not a new expense.

Provenance: see `../sources/whatsapp-learning-2026-08-11.md`.
