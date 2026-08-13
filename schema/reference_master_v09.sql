-- SPPG reference/master schema v0.9
-- Reference data is effective-dated; historical transactions keep the rules active at creation time.

create table if not exists sites (
  code text primary key,
  name text not null,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists entities (
  code text primary key,
  name text not null,
  entity_type text not null,
  active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists entity_site_roles (
  id bigserial primary key,
  entity_code text not null references entities(code),
  site_code text references sites(code),
  role_code text not null,
  effective_from date not null default current_date,
  effective_to date,
  unique(entity_code, site_code, role_code, effective_from)
);

create table if not exists vendor_rules (
  id bigserial primary key,
  vendor_code text not null references entities(code),
  site_code text references sites(code),
  category_code text,
  lead_time_days_before_cooking integer,
  payment_term_code text,
  payment_term_payload jsonb not null default '{}'::jsonb,
  internal_reimbursement boolean not null default false,
  intermediary_code text references entities(code),
  effective_from date not null,
  effective_to date,
  evidence_ref text,
  notes text,
  created_at timestamptz not null default now(),
  unique(vendor_code, site_code, category_code, effective_from)
);

create index if not exists idx_vendor_rules_lookup
  on vendor_rules(vendor_code, site_code, category_code, effective_from, effective_to);
