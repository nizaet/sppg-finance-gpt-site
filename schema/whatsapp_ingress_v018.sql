-- SPPG WhatsApp ingress v0.18
-- Incoming WhatsApp evidence is staged first and never mutates receiving/finance automatically.

create table if not exists whatsapp_sources (
  id bigserial primary key,
  source_key text not null unique,
  display_name text not null,
  site text not null,
  source_role text not null,
  active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (upper(site) in ('MAJA','CEMPLANG'))
);

insert into whatsapp_sources(source_key,display_name,site,source_role,metadata)
values
  (
    'MAJA_RECEIVING_GROUP',
    'DISTRIBUTOR BAHAN BAKU BGN SPPG MBG DAPUR YAYASAN DERMAWAN MENTARI MEGHA',
    'MAJA',
    'RECEIVING',
    '{"evidence_priority":"PRIMARY","notes":"Official kitchen receiving/distribution group for MAJA"}'::jsonb
  ),
  (
    'CEMPLANG_RECEIVING_GROUP',
    'DISTRIBUSI CEMPLANG 2',
    'CEMPLANG',
    'RECEIVING',
    '{"evidence_priority":"PRIMARY","notes":"Official kitchen receiving/distribution group for CEMPLANG"}'::jsonb
  )
on conflict (source_key) do update set
  display_name=excluded.display_name,
  site=excluded.site,
  source_role=excluded.source_role,
  active=true,
  metadata=excluded.metadata,
  updated_at=now();

create table if not exists whatsapp_inbox (
  id bigserial primary key,
  provider text not null,
  message_id text not null,
  source_key text references whatsapp_sources(source_key),
  group_name text,
  sender text,
  sender_name text,
  message_type text not null default 'text',
  text_body text,
  media_id text,
  media_mime_type text,
  media_sha256 text,
  provider_timestamp timestamptz,
  reported_date date,
  effective_date date,
  date_corrected boolean not null default false,
  date_correction_reason text,
  corrected_by text,
  event_type text,
  normalized_status text not null default 'STAGED',
  candidate_event_id bigint references candidate_events(id),
  raw_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(provider,message_id),
  check (normalized_status in ('STAGED','NEEDS_REVIEW','READY_FOR_RECEIVING_PREVIEW','MEDIA_PENDING','IGNORED','ERROR'))
);

create index if not exists idx_whatsapp_inbox_site_source
  on whatsapp_inbox(source_key, provider_timestamp desc);

create index if not exists idx_whatsapp_inbox_status
  on whatsapp_inbox(normalized_status, created_at desc);
