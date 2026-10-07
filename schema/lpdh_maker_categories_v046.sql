-- Correct only LPDH-export categories before approval. Never alter paid ledgers.
update accountant_invoices i
set invoice_category=case
  when d.document_type='BAHAN_BAKU' then 'BAHAN_BAKU'
  when d.document_type='INSENTIF_MITRA' then 'SEWA_MITRA'
  when d.document_type='UPAH_RELAWAN' and coalesce(d.header_payload->>'combinedPayments','false')='true' then 'UPAH'
  when d.document_type='UPAH_RELAWAN' then 'GAJI_RELAWAN'
  when d.document_type='INSENTIF_GURU_KADER' then 'UPAH'
  else 'OPERASIONAL_LAIN' end,
  updated_at=now()
from generated_document_maker_exports e
join generated_accountant_documents d on d.id=e.document_id
where i.id=e.accountant_invoice_id and i.source_type='LPDH_FINAL'
  and not exists(select 1 from bgn_makers m where m.accountant_invoice_id=i.id and upper(m.status) in ('PAID','APPROVED'))
  and not exists(select 1 from bgn_makers m join bgn_approvals a on a.bgn_maker_id=m.id where m.accountant_invoice_id=i.id and upper(a.status)='APPROVED')
  and not exists(select 1 from bgn_makers m join bgn_receipts r on r.bgn_maker_id=m.id where m.accountant_invoice_id=i.id);
