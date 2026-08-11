-- Planning bridge v0.10
-- Immutable-ish snapshots imported from Maja/Cemplang calculators.
-- A later snapshot may supersede an earlier one, but prior snapshots remain queryable.

create table if not exists planning_snapshots (
  id bigserial primary key,
  snapshot_key text not null unique,
  site text not null,
  distribution_date date not null,
  cooking_at timestamptz,
  source_system text not null,
  source_version text,
  source_updated_at timestamptz,
  production_cycle_id bigint references production_cycles(id),
  supersedes_snapshot_id bigint references planning_snapshots(id),
  status text not null default 'ACTIVE',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (status in ('ACTIVE','SUPERSEDED','REJECTED'))
);

create table if not exists planning_snapshot_items (
  id bigserial primary key,
  planning_snapshot_id bigint not null references planning_snapshots(id),
  item_code text,
  item_name text not null,
  category_code text,
  planned_qty numeric(18,4),
  unit text,
  planning_price numeric(18,2),
  preferred_vendor_code text,
  notes text,
  source_payload jsonb not null default '{}'::jsonb
);

create index if not exists idx_planning_snapshots_site_date
  on planning_snapshots(site, distribution_date, created_at desc);
create index if not exists idx_planning_snapshot_items_snapshot
  on planning_snapshot_items(planning_snapshot_id);
