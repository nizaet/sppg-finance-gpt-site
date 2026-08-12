-- SPPG inventory ledger v0.14
-- Inventory movements are operational stock facts, not finance transactions.

alter table inventory_movements
  add column if not exists source_type text,
  add column if not exists source_key text,
  add column if not exists source_ref text,
  add column if not exists notes text;

create unique index if not exists uq_inventory_movements_source_key
  on inventory_movements(source_key)
  where source_key is not null;

create index if not exists idx_inventory_movements_balance
  on inventory_movements(item_name, from_location, to_location, occurred_at);
