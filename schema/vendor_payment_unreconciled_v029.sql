-- SPPG vendor payment override v0.29
-- A verified transfer is a financial fact even when invoice/GR reconciliation is incomplete.
-- Keep payment occurrence separate from reconciliation linkage and preserve evidence/audit metadata.

alter table vendor_payments
  add column if not exists candidate_purchase_order_id bigint references purchase_orders(id),
  add column if not exists candidate_goods_receipt_id bigint references goods_receipts(id),
  add column if not exists candidate_vendor_invoice_id bigint references vendor_invoices(id),
  add column if not exists reconciliation_note text,
  add column if not exists source_external_id text,
  add column if not exists actor text,
  add column if not exists reconciled_at timestamptz;

create index if not exists idx_vendor_payments_unreconciled
  on vendor_payments(site,vendor_code,paid_at,id)
  where payment_status='PAID_UNRECONCILED';

create index if not exists idx_vendor_payments_candidates
  on vendor_payments(candidate_purchase_order_id,candidate_goods_receipt_id,candidate_vendor_invoice_id)
  where vendor_invoice_id is null;
