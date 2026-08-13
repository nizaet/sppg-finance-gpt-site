-- SPPG Finance bridge schema v0.11
-- PostgreSQL mirror/audit layer for ChatGPT -> Firestore finance transactions.

create table if not exists finance_transactions (
  id bigserial primary key,
  transaction_id text not null unique,
  idempotency_key text not null unique,
  site text not null,
  transaction_date date not null,
  description text not null,
  transaction_type text not null check (transaction_type in ('income','expense')),
  category text not null,
  amount numeric(18,2) not null check (amount >= 0),
  qty numeric(18,4),
  unit text,
  unit_price numeric(18,2),
  order_by text,
  is_debt boolean not null default false,
  payment_status text not null default 'paid' check (payment_status in ('paid','unpaid','partial')),
  paid_amount numeric(18,2) not null default 0,
  paid_date date,
  source text not null default 'chatgpt_bridge',
  source_ref text,
  raw_text text,
  classification_confidence numeric(5,4),
  classification_reason text,
  note text,
  firestore_doc_id text,
  firestore_sync_status text not null default 'PENDING',
  firestore_sync_error text,
  evidence_uri text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_finance_transactions_site_date
  on finance_transactions(site, transaction_date desc);

create index if not exists idx_finance_transactions_payment
  on finance_transactions(site, payment_status, transaction_date desc);

create table if not exists finance_bridge_audit_log (
  id bigserial primary key,
  transaction_id text,
  action text not null,
  actor text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
