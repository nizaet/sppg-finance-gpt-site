-- Vendor payment workflow v0.16
-- Payment evidence changes payable status only; finance ledger creation is a separate confirmed step.

alter table vendor_payments
  add column if not exists source_key text;

create unique index if not exists ux_vendor_payments_source_key
  on vendor_payments(source_key)
  where source_key is not null;

create index if not exists idx_vendor_payments_invoice_status
  on vendor_payments(vendor_invoice_id,payment_status,paid_at);
