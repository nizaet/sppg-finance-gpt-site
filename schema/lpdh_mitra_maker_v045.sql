-- Preserve documents; add the independent Mitra incentive invoice and export identity.
alter table generated_accountant_documents drop constraint if exists generated_accountant_documents_document_type_check;
alter table generated_accountant_documents add constraint generated_accountant_documents_document_type_check
  check(document_type in ('BAHAN_BAKU','OPERASIONAL','INSENTIF_GURU_KADER','UPAH_RELAWAN','INSENTIF_MITRA'));
create table if not exists generated_document_maker_exports (
  document_id bigint primary key references generated_accountant_documents(id),
  accountant_invoice_id bigint not null references accountant_invoices(id),
  maker_id bigint references bgn_makers(id) on delete set null,
  exported_by text not null,
  exported_at timestamptz not null default now()
);
alter table generated_document_maker_exports alter column maker_id drop not null;
alter table generated_document_maker_exports drop constraint if exists generated_document_maker_exports_maker_id_fkey;
alter table generated_document_maker_exports add constraint generated_document_maker_exports_maker_id_fkey
  foreign key(maker_id) references bgn_makers(id) on delete set null;
-- User-confirmed policy: these two kitchens have no additional cost-index compensation.
update lpdh_site_state set data=jsonb_set(data,'{parameters}',coalesce(data->'parameters','{}'::jsonb) ||
  '{"operationalPerPm":3000,"applyIndexRaw":false,"applyIndexOp":false,"cityIndex":1,"noIndexCompensation":true}'::jsonb)
where site in ('MAJA','CEMPLANG');
