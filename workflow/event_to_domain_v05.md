# Event to Domain Mapping v0.5

This file is the implementation contract between validated candidate events and SPPG Core domain tables.

| Candidate event | Domain effect |
|---|---|
| PO_NEW | create `purchase_orders` + `purchase_order_items` revision 1 |
| PO_REVISION | create new `purchase_orders` revision linked via `supersedes_po_id`; never mutate prior revision quantities/prices |
| PO_ACKNOWLEDGED | set acknowledgement metadata/status only |
| GOODS_RECEIVED | create `goods_receipts` + `goods_receipt_items` |
| QUALITY_REJECT_REPORTED | update reconciliation through a new receipt/reject record or controlled correction; preserve raw prior state in audit |
| VENDOR_PRICE_CHANGED | create current price observation/config update; do not rewrite historical PO/invoice rows |
| VENDOR_INVOICE | create `vendor_invoices` + items using vendor cost/modal price |
| PAYMENT_INTENT | no `vendor_payments` paid row; create pending task/action only |
| PAYMENT_EVIDENCE_CANDIDATE | create/reconcile payment only after invoice, amount, beneficiary, site and evidence validate |
| KOPERASI_STOCK_TRANSFER_REQUEST | create planned internal movement; no expense |
| KOPERASI_STOCK_TRANSFER_CONFIRMED | create `inventory_movements` from KOPERASI to MAJA/CEMPLANG |
| INTERNAL_CASH_PURCHASE | create cost record + `internal_reimbursements` pending when applicable |
| ACTUAL_USAGE_FINALIZED | create/version `actual_usage` with actual_used_qty and distinct vendor_cost_price/claim_price |
| ACCOUNTANT_EXCEL_SENT | create `accountant_submissions` |
| ACCOUNTANT_INVOICE_RECEIVED | create `accountant_invoices` |
| BGN_MAKER_CREATED | create `bgn_makers` |
| APPROVAL_LIST_SENT | create/request `bgn_approvals` pending |
| APPROVAL_CONFIRMED | advance matching `bgn_approvals`; do not approve unmatched maker references |
| BGN_FUNDS_RECEIVED | create `bgn_receipts` |
| SETTLEMENT_TO_OPERATIONAL | create `settlements`; never expense again |

## Required invariants

1. `planned_qty`, `po_qty`, `received_qty`, `actual_used_qty` are different facts.
2. `planning_price`, `po_price`, `vendor_cost_price`, `claim_price` are different facts.
3. Internal stock transfer never creates a second procurement expense.
4. Yayasan/Koperasi -> BCA Operational settlement never creates a second expense.
5. A payment intention is never proof of payment.
6. A vendor acknowledgement is never proof of receipt.
7. Approval list sent is never approval confirmed.
8. Revision and correction are versioned/audited rather than silent overwrites.
9. Every final-domain mutation must be traceable to operator input or validated evidence/candidate event.
