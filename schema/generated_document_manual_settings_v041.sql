-- Private artwork and saved defaults are isolated from existing master/payment data.
create table if not exists generated_document_assets (
  id bigserial primary key,
  site text not null check(site in ('MAJA','CEMPLANG')),
  asset_kind text not null check(asset_kind in ('LETTERHEAD','STAMP','SIGNATURE','RECIPIENT_SIGNATURE')),
  filename text not null,
  mime_type text not null,
  content bytea not null,
  created_by text not null,
  created_at timestamptz not null default now()
);
create table if not exists generated_document_profiles (
  site text not null check(site in ('MAJA','CEMPLANG')),
  profile_key text not null check(profile_key in ('KOPERASI','YAYASAN')),
  header_payload jsonb not null,
  updated_by text not null,
  updated_at timestamptz not null default now(),
  primary key(site,profile_key)
);
create table if not exists generated_accountant_document_numbers (
  normalized_number text primary key,
  document_id bigint not null references generated_accountant_documents(id),
  number_kind text not null check(number_kind in ('DOCUMENT','RECEIPT'))
);
insert into generated_accountant_document_numbers(normalized_number,document_id,number_kind)
  select lower(btrim(document_number)),id,'DOCUMENT' from generated_accountant_documents
  on conflict(normalized_number) do nothing;
with receipts as (
  select d.id as document_id,d.document_number,i.item_payload,
         row_number() over(partition by d.id order by i.id) as sequence
  from generated_accountant_documents d join generated_accountant_document_items i on i.document_id=d.id
  where d.document_type in ('UPAH_RELAWAN','INSENTIF_GURU_KADER')
)
insert into generated_accountant_document_numbers(normalized_number,document_id,number_kind)
  select lower(coalesce(nullif(btrim(item_payload->>'receiptNo'),''),document_number||'-'||lpad(sequence::text,3,'0'))),document_id,'RECEIPT' from receipts
  on conflict(normalized_number) do nothing;
