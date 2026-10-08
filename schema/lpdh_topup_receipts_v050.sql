create table if not exists lpdh_topup_receipt_profiles (
 site text primary key check(site in ('MAJA','CEMPLANG')),
 data jsonb not null default '{}', updated_at timestamptz not null default now()
);
create table if not exists lpdh_topup_receipts (
 id bigserial primary key, site text not null check(site in ('MAJA','CEMPLANG')),
 service_date date not null, document_number text not null,
 status text not null default 'DRAFT' check(status in ('DRAFT','FINAL','CANCELLED')),
 snapshot jsonb not null, pdf_link text, cancelled_reason text,
 created_by text not null, finalized_by text, finalized_at timestamptz,
 updated_at timestamptz not null default now()
);
create index if not exists lpdh_topup_receipts_day on lpdh_topup_receipts(site,service_date);

