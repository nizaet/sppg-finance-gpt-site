-- SPPG vendor payable extension v0.13
-- Keep planning, PO, receiving, payable and finance layers separate.

alter table vendor_invoices
  add column if not exists purchase_order_id bigint references purchase_orders(id),
  add column if not exists goods_receipt_id bigint references goods_receipts(id),
  add column if not exists payable_status text not null default 'UNPAID',
  add column if not exists due_date date,
  add column if not exists source_key text,
  add column if not exists updated_at timestamptz not null default now();

create unique index if not exists ux_vendor_invoices_source_key
  on vendor_invoices(source_key)
  where source_key is not null;

alter table vendor_invoice_items
  add column if not exists purchase_order_item_id bigint references purchase_order_items(id),
  add column if not exists goods_receipt_item_id bigint references goods_receipt_items(id),
  add column if not exists accepted_qty_snapshot numeric(18,4),
  add column if not exists updated_at timestamptz not null default now();

alter table vendor_payments
  add column if not exists due_date date,
  add column if not exists reference_number text,
  add column if not exists finance_transaction_id text,
  add column if not exists updated_at timestamptz not null default now();

create index if not exists idx_vendor_invoices_status_due
  on vendor_invoices(site, vendor_code, payable_status, due_date);
