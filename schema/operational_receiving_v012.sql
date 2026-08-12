-- SPPG operational receiving bridge v0.12
-- WhatsApp/chat is evidence for receiving; PO/planning quantities remain immutable layers.

alter table purchase_orders
  add column if not exists finalized_at timestamptz,
  add column if not exists source_planning_snapshot_id bigint references planning_snapshots(id),
  add column if not exists updated_at timestamptz not null default now();

alter table purchase_order_items
  add column if not exists planning_snapshot_item_id bigint references planning_snapshot_items(id),
  add column if not exists item_aliases jsonb not null default '[]'::jsonb,
  add column if not exists updated_at timestamptz not null default now();

alter table goods_receipts
  add column if not exists source_type text not null default 'MANUAL',
  add column if not exists source_external_id text,
  add column if not exists source_key text,
  add column if not exists reporter text,
  add column if not exists raw_text text,
  add column if not exists match_status text not null default 'CONFIRMED',
  add column if not exists match_confidence numeric(6,5),
  add column if not exists confirmed_at timestamptz,
  add column if not exists updated_at timestamptz not null default now();

create unique index if not exists uq_goods_receipts_source_key
  on goods_receipts(source_key)
  where source_key is not null;

alter table goods_receipt_items
  add column if not exists reported_item_name text,
  add column if not exists po_qty_snapshot numeric(18,4),
  add column if not exists variance_qty numeric(18,4),
  add column if not exists match_confidence numeric(6,5),
  add column if not exists match_method text,
  add column if not exists updated_at timestamptz not null default now();

create index if not exists idx_purchase_orders_site_vendor_status
  on purchase_orders(site, vendor_code, status);

create index if not exists idx_goods_receipts_po_received
  on goods_receipts(purchase_order_id, received_at desc);

create index if not exists idx_goods_receipt_items_po_item
  on goods_receipt_items(purchase_order_item_id);
