-- Additive: old evidence, serial claims, and FINAL snapshots remain intact.
create table if not exists document_number_anchors (
  site text not null check(site in ('MAJA','CEMPLANG')),
  namespace text not null,
  full_number text not null,
  owner_key text not null,
  selected_at timestamptz not null default now(),
  primary key(site,namespace)
);
-- Existing records have no separate number-edit timestamp. Use the most
-- recently saved document/day once; future anchors change only on number edits.
insert into document_number_anchors(site,namespace,full_number,owner_key,selected_at)
select distinct on(site,namespace) site,namespace,full_number,owner_key,selected_at
from (
  select site,document_type as namespace,document_number as full_number,
         'DOC:'||id::text as owner_key,updated_at as selected_at
  from generated_accountant_documents where btrim(document_number) ~ '^[0-9]+/.+'
  union all
  select site,'LPDH',data->>'lpdhNumber','DAY:'||service_date::text,updated_at
  from lpdh_daily_state where btrim(data->>'lpdhNumber') ~ '^[0-9]+/.+'
) candidates order by site,namespace,selected_at desc,owner_key desc
on conflict(site,namespace) do nothing;
alter table generated_accountant_documents add column if not exists drive_excel_uri text;
alter table generated_accountant_documents add column if not exists drive_folder_id text;
