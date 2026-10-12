create table if not exists lpdh_bgn_drive_connections (
  site text primary key check(site in ('MAJA','CEMPLANG')),
  email text not null,
  token_ciphertext text not null,
  folder_id text,
  connected_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists lpdh_bgn_drive_oauth_states (
  state_hash text primary key,
  browser_hash text not null,
  site text not null check(site in ('MAJA','CEMPLANG')),
  verifier text not null,
  expires_at timestamptz not null
);
create table if not exists lpdh_bgn_drive_uploads (
  site text not null check(site in ('MAJA','CEMPLANG')),
  artifact_key text not null,
  content_hash text not null,
  file_id text not null,
  folder_id text not null,
  drive_uri text not null,
  service_date date not null,
  uploaded_at timestamptz not null default now(),
  primary key(site,artifact_key,content_hash)
);

