# Actual goods receipts and corrections

Operator requirement (2026-10-18): input actual quantity per arrived item instead of always accepting the entire PO; allow correction after an accidental confirmation. Applies to [MAJA](../sites/maja.md) and [CEMPLANG](../sites/cemplang.md).

- **Catat datang** records a new arrival quantity. It adds to prior receipts. Partial delivery leaves the PO partially received; overdelivery is shown in the confirmation without changing the ordered quantity.
- **Sesuai / Semua sesuai** records the remaining PO quantity. These shortcuts remain available.
- **Ubah penerimaan** edits actual arrived/rejected quantities of an existing receipt, including a completed PO. Zero reverses a mistakenly confirmed arrival. Each correction needs an explicit reason and a before/after confirmation.
- The original report, PO quantities, invoice snapshots and payment amounts are preserved. Before/after receipt values and reason are appended to the operational audit log. Changed current receipt quantities remain separate from the immutable ordered and invoiced layers.
- Inventory gets a compensating movement for the accepted-quantity delta. The original posting remains intact. The correction uses the original arrival's locations, item identity, unit and effective timestamp. A newer physical SO continues to anchor current stock. A real return today or a fresh physical count is a different workflow.
- [Koperasi transfers](koperasi-flow.md) reverse the delta between the same warehouses; they do not create an expense.
- Linked invoices are flagged for review, including paid ones. Correcting receipt quantities does not silently change an invoice, payment, or Accountant transaction.
- Per-request idempotency, PO/receipt locks and stale-value/version checks prevent replay and conflicting edits. Stock projections are invalidated after successful writes; see [PO warehouse scope](po-reminder-stock-scope.md).

Implementation: `backend/po_receiving_confirmation_api.py`, `backend/inventory_api.py`, `src/operations/PoReceivingConfirm.jsx`, `src/operations/GoodsReceiptEditor.jsx`, and `src/operations/OperationsReceiving.jsx`.

Evidence: operator request in APP OPERASIONAL SPPG, 2026-10-18; `tests/test_goods_receipt_quantities.py` and `tests/receiving-quantities-ui.test.cjs`. Runtime transaction values remain in PostgreSQL; this page specifies workflow rather than ledger facts.
