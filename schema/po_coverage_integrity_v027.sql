-- PO coverage integrity v0.27
--
-- purchase_order_items is the operator-edited source of truth for a normal
-- single-distribution-date PO.  purchase_order_coverage_items is the dated
-- allocation layer used by reminder/audit.  Before this migration, editing a
-- DRAFT replaced purchase_order_items but left the single-day coverage items
-- stale.  That made a visible SENT PO look uncovered to reminder consumers.
--
-- Multi-day/range POs are intentionally NOT rewritten here: their dated
-- coverage allocations are authoritative and cannot be reconstructed safely
-- from the aggregated purchase_order_items rows.

create or replace function refresh_single_day_po_coverage(p_purchase_order_id bigint)
returns void
language plpgsql
as $$
declare
  v_coverage_count integer;
  v_coverage_id bigint;
begin
  if p_purchase_order_id is null then
    return;
  end if;

  select count(*), min(id)
    into v_coverage_count, v_coverage_id
  from purchase_order_coverage
  where purchase_order_id = p_purchase_order_id;

  -- Creation/revision inserts the aggregate PO items before its coverage rows.
  -- Do nothing while coverage does not exist yet.  The create/revise workflow
  -- will populate it immediately afterwards.
  if v_coverage_count <> 1 then
    return;
  end if;

  delete from purchase_order_coverage_items
  where purchase_order_coverage_id = v_coverage_id;

  insert into purchase_order_coverage_items(
    purchase_order_coverage_id,
    planning_snapshot_item_id,
    item_code,
    item_name,
    planned_qty,
    po_qty,
    unit
  )
  select
    v_coverage_id,
    poi.planning_snapshot_item_id,
    poi.item_code,
    poi.item_name,
    poi.planned_qty,
    poi.po_qty,
    poi.unit
  from purchase_order_items poi
  where poi.purchase_order_id = p_purchase_order_id;
end;
$$;

create or replace function trg_refresh_single_day_po_coverage()
returns trigger
language plpgsql
as $$
begin
  perform refresh_single_day_po_coverage(
    case when tg_op = 'DELETE' then old.purchase_order_id else new.purchase_order_id end
  );
  return null;
end;
$$;

drop trigger if exists trg_po_items_refresh_single_day_coverage on purchase_order_items;
create trigger trg_po_items_refresh_single_day_coverage
after insert or update or delete on purchase_order_items
for each row execute function trg_refresh_single_day_po_coverage();

-- Repair legacy/current POs that have no explicit coverage row at all.  These
-- are single-cycle POs by definition; the base production-cycle date is the
-- only safe dated coverage we can infer.
insert into purchase_order_coverage(
  purchase_order_id,
  distribution_date,
  cooking_date,
  planning_snapshot_id
)
select
  po.id,
  pc.distribution_date,
  case when pc.cooking_at is null then null else date(pc.cooking_at) end,
  po.source_planning_snapshot_id
from purchase_orders po
join production_cycles pc on pc.id = po.production_cycle_id
where not exists (
  select 1 from purchase_order_coverage poc
  where poc.purchase_order_id = po.id
)
on conflict (purchase_order_id, distribution_date) do nothing;

-- Heal every existing single-day PO immediately on deployment, including POs
-- that are already FINALIZED/SENT.  This is the production backfill needed for
-- POs created before this invariant existed.
do $$
declare
  r record;
begin
  for r in
    select purchase_order_id
    from purchase_order_coverage
    group by purchase_order_id
    having count(*) = 1
  loop
    perform refresh_single_day_po_coverage(r.purchase_order_id);
  end loop;
end;
$$;
