-- LPDH workspace v0.38
-- Cloud-persistent master data, daily drafts, effective service days, and calculator-final snapshots.

create table if not exists lpdh_site_state (
  site text primary key,
  data jsonb not null default '{}'::jsonb,
  revision integer not null default 1,
  updated_by text,
  updated_at timestamptz not null default now(),
  check (upper(site) in ('MAJA','CEMPLANG'))
);

create table if not exists lpdh_daily_state (
  site text not null,
  service_date date not null,
  data jsonb not null default '{}'::jsonb,
  status text not null default 'DRAFT',
  revision integer not null default 1,
  updated_by text,
  updated_at timestamptz not null default now(),
  primary key (site, service_date),
  check (upper(site) in ('MAJA','CEMPLANG')),
  check (status in ('DRAFT','READY','GENERATED'))
);

create table if not exists lpdh_effective_days (
  site text not null,
  service_date date not null,
  is_effective boolean not null default true,
  note text,
  updated_by text,
  updated_at timestamptz not null default now(),
  primary key (site, service_date),
  check (upper(site) in ('MAJA','CEMPLANG'))
);

create table if not exists lpdh_final_plans (
  site text not null,
  service_date date not null,
  source_plan_id text,
  plan_name text,
  payload jsonb not null default '{}'::jsonb,
  revision integer not null default 1,
  finalized_by text,
  finalized_at timestamptz not null default now(),
  primary key (site, service_date),
  check (upper(site) in ('MAJA','CEMPLANG'))
);

create table if not exists lpdh_generation_log (
  id bigserial primary key,
  site text not null,
  service_date date not null,
  filename text not null,
  validation_status text not null,
  validation_error_count integer not null default 0,
  generated_by text,
  generated_at timestamptz not null default now(),
  payload jsonb not null default '{}'::jsonb,
  check (upper(site) in ('MAJA','CEMPLANG'))
);

create index if not exists idx_lpdh_daily_date on lpdh_daily_state(service_date desc, site);
create index if not exists idx_lpdh_effective_month on lpdh_effective_days(site, service_date);
create index if not exists idx_lpdh_generation_date on lpdh_generation_log(site, service_date desc, generated_at desc);
