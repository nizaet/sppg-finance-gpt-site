-- Read-only suggestions do not consume numbers. Claims survive cancellation/deletion.
create table if not exists document_number_serials (
  site text not null check(site in ('MAJA','CEMPLANG')),
  namespace text not null,
  serial bigint,
  full_number text not null,
  normalized_number text not null,
  owner_key text not null,
  created_at timestamptz not null default now(),
  primary key(site,namespace,normalized_number)
);
create index if not exists document_serial_lookup on document_number_serials(site,namespace,serial desc);
insert into document_number_serials(site,namespace,serial,full_number,normalized_number,owner_key)
  select site,document_type,
    case when btrim(document_number) ~ '^[0-9]{1,15}/.+' then split_part(btrim(document_number),'/',1)::bigint end,
    btrim(document_number),lower(btrim(document_number)),'DOC:'||id::text
  from generated_accountant_documents
  on conflict do nothing;
-- Preserve the legacy master number on its first saved day, without creating payments.
insert into document_number_serials(site,namespace,serial,full_number,normalized_number,owner_key)
  select s.site,'LPDH',
    case when btrim(s.data->'identity'->>'lpdhNumber') ~ '^[0-9]{1,15}/.+' then split_part(btrim(s.data->'identity'->>'lpdhNumber'),'/',1)::bigint end,
    btrim(s.data->'identity'->>'lpdhNumber'),lower(btrim(s.data->'identity'->>'lpdhNumber')),'DAY:'||d.first_date::text
  from lpdh_site_state s join (select site,min(service_date) as first_date from lpdh_daily_state group by site) d on d.site=s.site
  where nullif(btrim(s.data->'identity'->>'lpdhNumber'),'') is not null
    and not exists(select 1 from lpdh_daily_state x where x.site=s.site and x.service_date=d.first_date and nullif(btrim(x.data->>'lpdhNumber'),'') is not null)
  on conflict do nothing;
insert into document_number_serials(site,namespace,serial,full_number,normalized_number,owner_key)
  select site,'LPDH',
    case when btrim(data->>'lpdhNumber') ~ '^[0-9]{1,15}/.+' then split_part(btrim(data->>'lpdhNumber'),'/',1)::bigint end,
    btrim(data->>'lpdhNumber'),lower(btrim(data->>'lpdhNumber')),'DAY:'||service_date::text
  from lpdh_daily_state where nullif(btrim(data->>'lpdhNumber'),'') is not null
  on conflict do nothing;
