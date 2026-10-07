-- Companion paperwork never creates a second financial transaction.
create table if not exists lpdh_delivery_packages (
 document_id bigint primary key references generated_accountant_documents(id),
 site text not null,
 service_date date not null,
 numbers jsonb not null,
 settings jsonb not null default '{}'::jsonb,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create table if not exists lpdh_delivery_counters (
 site text not null, kind text not null, period text not null,
 value bigint not null default 0,
 primary key(site,kind,period)
);
