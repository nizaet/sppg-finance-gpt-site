# Pusat Operasional — Control Tower v0.8

## Purpose
Control Tower is the operational home screen for Maja and Cemplang. It summarizes what must be done today without collapsing distinct states into a single checkbox.

## Site cards
Each site card must show:
- production/distribution date
- menu/production cycle identifier
- planning readiness
- PO due / sent / revised / acknowledged
- goods received / reject unresolved
- vendor invoices pending
- vendor payments due / paid
- actual usage finalized
- final costing status
- accountant submission status
- accountant invoice status
- BGN maker status
- approval status
- BGN funds received status
- settlement to BCA Operational status

## Today queues
1. PO actions due today
2. Expected deliveries today
3. Reject/reconciliation requiring action
4. Vendor invoices awaiting reconciliation
5. Vendor payments due today
6. Internal reimbursements pending
7. Accountant files/invoices pending
8. Maker/approval pending
9. BGN receipts/settlement pending
10. Review Queue events requiring operator decision

## Invariants
- No one status may imply another status.
- `PO_SENT` does not mean `GOODS_RECEIVED`.
- `VENDOR_INVOICE_RECEIVED` does not mean `VENDOR_PAID`.
- `APPROVAL_LIST_SENT` does not mean `BGN_APPROVED`.
- `BGN_FUNDS_RECEIVED` does not mean `SETTLED_TO_OPERATIONAL`.
- Internal stock transfer is never displayed as a vendor expense.

## Operational priority
Sort by:
1. overdue critical action
2. action due today
3. action due next
4. informational status

Critical items include cooking-risk PO, missing delivery, unresolved reject that changes payable amount, payment evidence mismatch, maker/approval deadline, and settlement mismatch.
