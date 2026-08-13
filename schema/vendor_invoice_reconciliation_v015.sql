-- SPPG vendor invoice reconciliation v0.15
-- Vendor invoice quantity may differ from PO/receipt quantity; rejects reduce payable only.

alter table vendor_invoice_items
  add column if not exists rejected_qty numeric(18,4) not null default 0,
  add column if not exists payable_qty numeric(18,4),
  add column if not exists reject_amount numeric(18,2) not null default 0,
  add column if not exists po_qty_snapshot numeric(18,4),
  add column if not exists invoice_vs_po_variance numeric(18,4),
  add column if not exists invoice_vs_receipt_variance numeric(18,4);

create index if not exists idx_vendor_invoice_items_receipt
  on vendor_invoice_items(goods_receipt_item_id);
