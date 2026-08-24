-- Track the exact Calculator-plan content used to generate Accountant Excel v0.32
alter table accountant_submissions
  add column if not exists source_plan_hash text,
  add column if not exists source_plan_updated_at timestamptz;

create index if not exists idx_accountant_submission_plan_hash
  on accountant_submissions(source_calculator_document_id, source_plan_hash)
  where source_calculator_document_id is not null;
