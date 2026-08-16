-- Multi-day purchase-order coverage v0.24.
-- One vendor message may cover several distribution dates while preserving
-- the per-day planning quantities used by reminders and audit.

create table if not exists purchase_order_coverage (
  id bigserial primary key,
  purchase_order_id bigint not null references purchase_orders(id) on delete cascade,
  distribution_date date not null,
  cooking_date date,
  planning_snapshot_id bigint references planning_snapshots(id),
  created_at timestamptz not null default now(),
  unique(purchase_order_id, distribution_date)
);

create table if not exists purchase_order_coverage_items (
  id bigserial primary key,
  purchase_order_coverage_id bigint not null references purchase_order_coverage(id) on delete cascade,
  planning_snapshot_item_id bigint references planning_snapshot_items(id),
  item_code text,
  item_name text not null,
  planned_qty numeric(18,4),
  po_qty numeric(18,4) not null default 0,
  unit text,
  created_at timestamptz not null default now()
);

create index if not exists idx_po_coverage_date
  on purchase_order_coverage(distribution_date, purchase_order_id);

create index if not exists idx_po_coverage_items_po
  on purchase_order_coverage_items(purchase_order_coverage_id);
