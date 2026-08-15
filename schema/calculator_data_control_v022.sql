-- Calculator master data control and immutable import audit v0.22.
-- Firestore remains the calculator data store. PostgreSQL keeps the searchable
-- catalog and every before/after import event so classification and recovery do
-- not depend on rewriting the original evidence.

create table if not exists calculator_master_catalog (
  id bigserial primary key,
  site text not null,
  source_type text not null,
  source_document_key text not null,
  record_key text not null,
  canonical_name text not null,
  normalized_name text not null,
  category_code text,
  unit text,
  source_hash text not null,
  source_payload jsonb not null default '{}'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (site, source_type, record_key),
  check (site in ('MAJA','CEMPLANG')),
  check (source_type in ('PRICE','GRAMASI','RECIPE','RECIPE_INGREDIENT','PLAN_ITEM'))
);

create index if not exists idx_calculator_master_catalog_lookup
  on calculator_master_catalog(site, normalized_name) where active=true;

create index if not exists idx_calculator_master_catalog_document
  on calculator_master_catalog(site, source_type, source_document_key);

create table if not exists calculator_import_events (
  id bigserial primary key,
  site text not null,
  data_type text not null,
  record_key text not null,
  record_date date,
  source_ref text not null,
  source_hash text not null,
  target_path text,
  outcome text not null default 'PENDING',
  previous_payload jsonb,
  imported_payload jsonb not null,
  error_message text,
  created_by text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  check (site in ('MAJA','CEMPLANG')),
  check (data_type in ('PRICES','GRAMASI','RECIPES','DAILY_PLANS')),
  check (outcome in ('PENDING','COMMITTED','SKIPPED_EXISTING','FAILED'))
);

create index if not exists idx_calculator_import_events_site_created
  on calculator_import_events(site, created_at desc);

create index if not exists idx_calculator_import_events_record
  on calculator_import_events(site, data_type, record_key, created_at desc);
