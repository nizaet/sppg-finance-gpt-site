-- SPPG Core staging schema v0.5
-- Candidate events never mutate financial ledger directly.

create table if not exists ingest_sources (
  id bigserial primary key,
  source_type text not null,
  external_id text,
  source_uri text,
  source_hash text,
  received_at timestamptz not null default now(),
  unique (source_type, external_id)
);

create table if not exists candidate_events (
  id bigserial primary key,
  event_key text not null unique,
  source_id bigint references ingest_sources(id),
  event_type text not null,
  site text,
  vendor_code text,
  entity_code text,
  event_time timestamptz,
  confidence numeric(5,4),
  requires_confirmation boolean not null default true,
  payload jsonb not null default '{}'::jsonb,
  raw_text text,
  parser_version text,
  status text not null default 'PENDING',
  created_at timestamptz not null default now(),
  validated_at timestamptz,
  validated_by text,
  rejection_reason text,
  check (status in ('PENDING','VALIDATED','REJECTED','APPLIED','SUPERSEDED'))
);

create table if not exists workflow_actions (
  id bigserial primary key,
  candidate_event_id bigint not null references candidate_events(id),
  action_type text not null,
  target_type text not null,
  target_id text,
  action_payload jsonb not null default '{}'::jsonb,
  status text not null default 'PLANNED',
  created_at timestamptz not null default now(),
  applied_at timestamptz,
  applied_by text,
  idempotency_key text not null unique,
  check (status in ('PLANNED','READY','APPLIED','FAILED','CANCELLED'))
);

create table if not exists event_audit_log (
  id bigserial primary key,
  candidate_event_id bigint references candidate_events(id),
  workflow_action_id bigint references workflow_actions(id),
  action text not null,
  actor text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_candidate_events_status on candidate_events(status);
create index if not exists idx_candidate_events_type on candidate_events(event_type);
create index if not exists idx_candidate_events_site_vendor on candidate_events(site, vendor_code);
create index if not exists idx_workflow_actions_status on workflow_actions(status);
