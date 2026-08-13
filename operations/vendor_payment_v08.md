# Vendor Payment Workflow v0.8

## Principle
Payment is a reconciliation process, not a checkbox copied from a PO or invoice.

## Amount layers
- invoice_gross_amount
- reject_deduction_amount
- other_adjustment_amount
- net_payable_amount
- paid_amount
- outstanding_amount

`net_payable_amount = invoice_gross_amount - reject_deduction_amount +/- other_adjustment_amount`

## Payment lifecycle
INVOICE_PENDING_RECONCILIATION
→ PAYABLE_CONFIRMED
→ PAYMENT_DUE
→ PAYMENT_INTENT
→ PAYMENT_EVIDENCE_SUBMITTED
→ PAYMENT_RECONCILED
→ PAID

## Evidence gates
- Text such as `nanti saya transfer` = PAYMENT_INTENT only.
- Text such as `sudah transfer` = PAYMENT_EVIDENCE_CANDIDATE; payment is not final without matching amount/account/reference or explicit operator reconciliation.
- Bank proof may satisfy evidence but still requires matching to vendor + payable.
- Partial payment must remain partial; do not force PAID.

## Vendor-specific configuration
Payment cadence is configurable and versioned:
- daily
- weekly
- after delivery
- H+n
- custom weekday
- cash purchase + month-end internal reimbursement

Do not hard-code payment terms from old assumptions. Use current vendor master/evidence.

## Internal cash flows
Tempe/tahu Maja and telur via Mungki may be cash purchases followed by internal month-end reimbursement. These are not ordinary vendor bank-payment flows and are not BGN reimbursement.

## Koperasi
Koperasi dry-goods dispatch to kitchen is stock transfer and must not appear in vendor payment queue. Indogrosir procurement into Koperasi inventory may create a payable at Koperasi level.

## Control Tower fields
- site
- vendor
- invoice/reference
- invoice_gross_amount
- reject_deduction_amount
- net_payable_amount
- due_at
- payment_status
- paid_amount
- outstanding_amount
- evidence_status
- evidence_reference
- reconciliation_notes
