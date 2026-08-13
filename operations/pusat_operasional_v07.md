# Pusat Operasional v0.7

## Scope
Pusat Operasional is the orchestration layer. The existing Maja and Cemplang menu calculators remain the planning/calculation source and should not be rewritten in this phase.

## Primary screens
1. Hari Ini / Control Tower
2. Kalender Produksi
3. PO & Supplier
4. Penerimaan & Reject
5. Pembayaran Vendor
6. Actual Usage & Final Costing
7. Akuntan
8. BGN Maker & Approval
9. Koperasi / Gudang
10. Review Queue
11. Audit Trail

## Control Tower
For every production cycle show:
- site
- distribution date
- cooking datetime
- menu/planning status
- PO due/sent/acknowledged/revised
- goods received/reject pending
- vendor invoice/payment due/paid
- actual usage finalized
- accountant Excel sent
- accountant invoice received
- maker created
- approval pending/approved
- BGN funds received
- settlement to BCA operational

## Calculator boundary
- Read planning/menu/calculation snapshots from Maja/Cemplang calculators.
- Pusat Operasional may edit `po_qty` without mutating calculator `planned_qty`.
- Pusat Operasional may edit supplier assignment without rewriting historical calculator output.
- Final accountant export uses final costing data while preserving the calculator presentation/template expected by accounting.

## Lead-time scheduler
All procurement deadlines are anchored to cooking time, not distribution date.
Initial known rules:
- sayur/buah: H-1 cooking
- tempe: H-2 cooking
- ayam: H-3 cooking
Lead times remain configurable by vendor/category/site.

## Review Queue
Must prominently surface:
- payment evidence candidates
- BGN approvals
- settlement evidence
- low/medium confidence parser output
- conflicting quantities/prices
- unmatched vendors/items/sites
- rejected/BS quantities not yet reconciled

## Financial safeguards
- Payment intent is never paid status.
- Approval-list sent is never approved status.
- Internal Koperasi stock transfer is never a second expense.
- Yayasan/Koperasi -> BCA Operational is settlement, not new income/expense.
- Historical quantity and price layers are append/revision based, not overwritten.

## Migration strategy
1. Keep calculators stable.
2. Build Pusat Operasional against API contract.
3. Run new backend in shadow/read-only mode against test data.
4. Validate PO/payment/stock/costing outcomes.
5. Enable writes module-by-module, starting with non-financial workflow states.
6. Enable financial writes only after review/audit gates are proven.
