-- Generated accountant invoice and daily receipt documents v0.1
-- Additive only: preserves existing purchase, maker, and operational tables.

create table if not exists generated_accountant_documents (
  id bigserial primary key,
  site text not null check (site in ('MAJA','CEMPLANG')),
  document_type text not null check (document_type in ('BAHAN_BAKU','OPERASIONAL','INSENTIF_GURU_KADER','UPAH_RELAWAN')),
  document_number text not null unique,
  service_date date not null,
  status text not null default 'DRAFT' check (status in ('DRAFT','FINAL')),
  header_payload jsonb not null default '{}'::jsonb,
  total_amount numeric(18,2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists generated_accountant_document_items (
  id bigserial primary key,
  document_id bigint not null references generated_accountant_documents(id) on delete cascade,
  item_name text not null,
  category_code text not null default 'LAIN_LAIN',
  quantity numeric(18,4) not null,
  unit text not null,
  unit_price numeric(18,2) not null default 0,
  line_total numeric(18,2) not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists idx_generated_docs_site_date
  on generated_accountant_documents(site, service_date desc, id desc);
create index if not exists idx_generated_doc_items_document
  on generated_accountant_document_items(document_id, id);
