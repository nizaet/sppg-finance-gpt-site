-- Preserve cancelled snapshots, but only active documents reserve an invoice number.
alter table generated_accountant_documents drop constraint if exists generated_accountant_documents_document_number_key;
create unique index if not exists uq_generated_active_document_number on generated_accountant_documents(document_number) where status <> 'CANCELLED';
delete from generated_accountant_document_numbers n using generated_accountant_documents d
where n.document_id=d.id and d.status='CANCELLED'
and not exists(select 1 from generated_document_maker_exports e where e.document_id=d.id and e.accountant_invoice_id is not null);
delete from document_number_serials s using generated_accountant_documents d
where s.owner_key='DOC:'||d.id::text and d.status='CANCELLED'
and not exists(select 1 from generated_document_maker_exports e where e.document_id=d.id and e.accountant_invoice_id is not null);
create table if not exists lpdh_delivery_profiles (
 site text not null, kind text not null check(kind in ('PO','SJ','CKL','KUI')),
 settings jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now(),
 primary key(site,kind)
);
