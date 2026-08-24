-- SPPG stock opname and canonical inventory master v0.21
-- Raw WhatsApp text and raw item labels are immutable evidence. Canonical
-- classification may be assigned through the master without rewriting them.

create table if not exists inventory_item_master (
  code text primary key,
  canonical_name text not null,
  normalized_canonical_name text not null unique,
  category_code text,
  base_unit text,
  active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists inventory_item_aliases (
  id bigserial primary key,
  inventory_item_code text not null references inventory_item_master(code),
  alias_text text not null,
  normalized_alias text not null unique,
  brand text,
  created_at timestamptz not null default now()
);

create table if not exists stock_opnames (
  id bigserial primary key,
  location_code text not null,
  site text,
  stock_date date not null,
  source_type text not null default 'WHATSAPP',
  source_external_id text,
  source_key text not null unique,
  reporter text,
  raw_text text not null,
  warning_count integer not null default 0,
  created_by text,
  created_at timestamptz not null default now(),
  check (location_code in ('KOPERASI','MAJA','CEMPLANG')),
  check (site is null or site in ('MAJA','CEMPLANG'))
);

create table if not exists stock_opname_items (
  id bigserial primary key,
  stock_opname_id bigint not null references stock_opnames(id),
  area_code text,
  inventory_item_code text references inventory_item_master(code),
  canonical_item_name text not null,
  raw_item_name text not null,
  normalized_raw_name text not null,
  qty numeric(18,4) not null,
  unit text,
  classification_status text not null default 'UNMAPPED',
  classification_method text,
  classification_confidence numeric(6,5),
  parse_status text not null default 'READY',
  raw_line text,
  warnings jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_stock_opnames_location_date
  on stock_opnames(location_code, stock_date desc, created_at desc);

create index if not exists idx_stock_opname_items_lookup
  on stock_opname_items(canonical_item_name, unit, stock_opname_id);

create index if not exists idx_inventory_item_aliases_master
  on inventory_item_aliases(inventory_item_code);
