-- SPPG historical operational provenance v0.17
-- Historical PO/receipt imports must remain distinguishable from live operational records.

alter table purchase_orders
  add column if not exists source_type text,
  add column if not exists source_external_id text,
  add column if not exists source_uri text,
  add column if not exists source_hash text,
  add column if not exists source_raw_text text,
  add column if not exists historical_import boolean not null default false;

create unique index if not exists uq_purchase_orders_source_hash
  on purchase_orders(source_hash)
  where source_hash is not null;

create index if not exists idx_purchase_orders_history_lookup
  on purchase_orders(site, vendor_code, historical_import, created_at desc);

alter table goods_receipts
  add column if not exists source_uri text,
  add column if not exists historical_import boolean not null default false;

create index if not exists idx_goods_receipts_history_lookup
  on goods_receipts(historical_import, purchase_order_id, received_at desc);
