-- Retain LPDH export provenance while the pending Maker/invoice flow is removed.
-- Original FINAL documents and Drive evidence are not deleted.
alter table generated_document_maker_exports alter column accountant_invoice_id drop not null;
alter table generated_document_maker_exports drop constraint if exists generated_document_maker_exports_accountant_invoice_id_fkey;
alter table generated_document_maker_exports add constraint generated_document_maker_exports_accountant_invoice_id_fkey
  foreign key(accountant_invoice_id) references accountant_invoices(id) on delete set null;
