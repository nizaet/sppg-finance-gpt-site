-- PO reminder manual resolution metadata v0.27
-- This table is intentionally separate from purchase_orders and inventory.
-- Operator overrides only resolve a reminder; they never mutate planning, PO,
-- receiving, stock, invoice, or payment source-of-truth records.

create table if not exists po_reminder_overrides (
  id bigserial primary key,
  reminder_key text not null,
  site text not null,
  vendor_code text not null,
  resolution text not null check (resolution in ('SUFFICIENT','MANUAL_PO')),
  note text,
  metadata jsonb not null default '{}'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists uq_po_reminder_overrides_active_key
  on po_reminder_overrides(reminder_key)
  where active = true;

create index if not exists idx_po_reminder_overrides_site_active
  on po_reminder_overrides(upper(site), active, updated_at desc);
