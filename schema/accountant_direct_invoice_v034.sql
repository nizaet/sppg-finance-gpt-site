-- Direct accountant invoices, document extraction and reusable approval evidence.

alter table accountant_invoices
  add column if not exists site text,
  add column if not exists accountant_code text,
  add column if not exists invoice_category text,
  add column if not exists invoice_date date,
  add column if not exists period_start date,
  add column if not exists period_end date,
  add column if not exists source_type text not null default 'EXCEL_RESPONSE',
  add column if not exists source_filename text,
  add column if not exists parsed_payload jsonb not null default '{}'::jsonb,
  add column if not exists parse_confidence numeric(5,4),
  add column if not exists updated_at timestamptz not null default now();

update accountant_invoices i
set site=coalesce(i.site,s.site), accountant_code=coalesce(i.accountant_code,s.accountant_code)
from accountant_submissions s
where s.id=i.accountant_submission_id and (i.site is null or i.accountant_code is null);

create index if not exists ix_accountant_invoices_site_date
  on accountant_invoices(site,invoice_date desc,id desc);

create table if not exists accountant_invoice_items (
  id bigserial primary key,
  accountant_invoice_id bigint not null references accountant_invoices(id) on delete cascade,
  item_name text not null,
  quantity numeric(18,4),
  unit text,
  unit_price numeric(18,2),
  line_total numeric(18,2),
  created_at timestamptz not null default now()
);

alter table bgn_approvals
  add column if not exists evidence_uri text,
  add column if not exists evidence_filename text,
  add column if not exists approval_method text;

create table if not exists approval_evidence_documents (
  id bigserial primary key,
  site text,
  source_filename text not null,
  evidence_uri text not null,
  document_date date,
  parsed_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists approval_evidence_matches (
  id bigserial primary key,
  document_id bigint not null references approval_evidence_documents(id) on delete cascade,
  bgn_maker_id bigint not null references bgn_makers(id),
  approval_id bigint references bgn_approvals(id),
  reference_number text,
  amount numeric(18,2),
  match_method text not null,
  match_confidence numeric(5,4),
  created_at timestamptz not null default now(),
  unique(document_id,bgn_maker_id)
);

