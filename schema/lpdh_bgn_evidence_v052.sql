-- New finalizations use BGN evidence; old archives remain untouched.
alter table generated_accountant_documents add column if not exists bgn_pdf_uri text;
alter table generated_accountant_documents add column if not exists bgn_upload_status text;
alter table generated_accountant_documents add column if not exists bgn_upload_error text;
alter table lpdh_topup_receipts add column if not exists internal_pdf_link text;
