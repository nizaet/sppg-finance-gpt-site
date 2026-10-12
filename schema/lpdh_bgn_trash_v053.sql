create table if not exists lpdh_bgn_trash_requests (
  id bigserial primary key,
  site text not null check(site in ('MAJA','CEMPLANG')),
  artifact_key text not null,
  file_id text not null,
  folder_id text not null,
  content_hash text not null,
  service_date date not null,
  requested_by text not null,
  status text not null default 'PENDING' check(status in ('PENDING','TRASHED','FAILED')),
  error_message text,
  requested_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(site,file_id)
);
