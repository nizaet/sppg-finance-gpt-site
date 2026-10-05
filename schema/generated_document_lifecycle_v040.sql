-- Preserve financial evidence and numbers; cancellation is not physical deletion.
alter table generated_accountant_documents drop constraint if exists generated_accountant_documents_status_check;
alter table generated_accountant_documents add constraint generated_accountant_documents_status_check
  check (status in ('DRAFT','FINAL','CANCELLED'));
alter table generated_accountant_documents add column if not exists cancelled_at timestamptz;
alter table generated_accountant_documents add column if not exists cancelled_by text;
alter table generated_accountant_documents add column if not exists cancellation_reason text;
alter table generated_accountant_documents add column if not exists drive_uri text;
alter table generated_accountant_documents add column if not exists drive_upload_status text;
alter table generated_accountant_documents add column if not exists drive_upload_error text;
