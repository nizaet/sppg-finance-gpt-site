-- SPPG accountant per-planning provenance v0.30
-- One accountant Excel may correspond to one calculator daily-plan document.

alter table accountant_submissions
  add column if not exists source_calculator_document_id text,
  add column if not exists source_plan_name text,
  add column if not exists source_distribution_date date,
  add column if not exists drive_upload_status text,
  add column if not exists drive_upload_error text,
  add column if not exists updated_at timestamptz not null default now();

create unique index if not exists uq_accountant_submission_calculator_plan
  on accountant_submissions(site, accountant_code, source_calculator_document_id)
  where source_calculator_document_id is not null;

alter table bgn_makers
  add column if not exists accountant_invoice_id bigint references accountant_invoices(id);

create unique index if not exists uq_bgn_maker_accountant_invoice
  on bgn_makers(accountant_invoice_id)
  where accountant_invoice_id is not null;
