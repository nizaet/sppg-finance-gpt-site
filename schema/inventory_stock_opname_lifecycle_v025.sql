-- Stock opname lifecycle v0.25
-- A physical SO must be removable from the active balance when it was entered
-- in error, without destroying its evidence/audit trail.

alter table stock_opnames
  add column if not exists status text not null default 'ACTIVE';

alter table stock_opnames
  add column if not exists superseded_by_stock_opname_id bigint;

alter table stock_opnames
  add column if not exists voided_at timestamptz;

alter table stock_opnames
  add column if not exists void_reason text;

create index if not exists idx_stock_opnames_active_location_date
  on stock_opnames(location_code, stock_date desc, created_at desc)
  where status = 'ACTIVE';
