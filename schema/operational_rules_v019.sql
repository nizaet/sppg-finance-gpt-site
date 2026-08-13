-- SPPG operational rules v0.19
-- Effective 2026-08-13. Preserve prior rules for historical reconstruction.
-- Confirmed operating rules:
--   vegetables/fruit via Holil: order H-2 before cooking/distribution cycle
--   chicken via Wikian: H-3 (already represented in v0.14)
--   dry goods from Koperasi: H-1
--   Holil and tofu/tempe payable on distribution day after distribution
--   fish / dori payable H+1

-- Close only currently-active rows that this migration supersedes.
update vendor_rules
set effective_to = date '2026-08-12'
where effective_to is null
  and effective_from < date '2026-08-13'
  and vendor_code='HOLIL'
  and site_code in ('MAJA','CEMPLANG')
  and category_code='SAYUR_BUAH';

update vendor_rules
set effective_to = date '2026-08-12'
where effective_to is null
  and effective_from < date '2026-08-13'
  and vendor_code='HAJI_BADRI'
  and site_code='CEMPLANG'
  and category_code='TAHU';

insert into vendor_rules(
  vendor_code,site_code,category_code,lead_time_days_before_cooking,
  payment_term_code,payment_term_payload,internal_reimbursement,intermediary_code,
  effective_from,evidence_ref,notes
) values
  ('HOLIL','MAJA','SAYUR_BUAH',2,
   'VENDOR_PAYABLE','{"payment_window":"DISTRIBUTION_DAY_AFTER_DISTRIBUTION","invoice_reconcile":true,"reject_deduction":true}'::jsonb,
   false,null,'2026-08-13','confirmed-operator-rule-2026-08-13',
   'Sayur/buah Holil dipesan H-2. Pembayaran dilakukan pada hari distribusi setelah distribusi, berdasarkan invoice/reject/netto.'),
  ('HOLIL','CEMPLANG','SAYUR_BUAH',2,
   'VENDOR_PAYABLE','{"payment_window":"DISTRIBUTION_DAY_AFTER_DISTRIBUTION","invoice_reconcile":true,"reject_deduction":true}'::jsonb,
   false,null,'2026-08-13','confirmed-operator-rule-2026-08-13',
   'Sayur/buah Holil dipesan H-2. Pembayaran dilakukan pada hari distribusi setelah distribusi, berdasarkan invoice/reject/netto.'),
  ('KOPERASI','MAJA','BAHAN_KERING',1,
   'INTERNAL_STOCK_TRANSFER','{"source":"KOPERASI","expense_created":false}'::jsonb,
   false,'MUNGKI','2026-08-13','confirmed-operator-rule-2026-08-13',
   'Bahan kering dipenuhi dari stok Koperasi H-1. Dispatch internal bukan pengeluaran baru.'),
  ('KOPERASI','CEMPLANG','BAHAN_KERING',1,
   'INTERNAL_STOCK_TRANSFER','{"source":"KOPERASI","expense_created":false}'::jsonb,
   false,'MUNGKI','2026-08-13','confirmed-operator-rule-2026-08-13',
   'Bahan kering dipenuhi dari stok Koperasi H-1. Dispatch internal bukan pengeluaran baru.'),
  ('RUMAH_DUTA_PANGAN','MAJA','IKAN',null,
   'VENDOR_PAYABLE','{"payment_window":"H_PLUS_1_AFTER_DISTRIBUTION","invoice_reconcile":true}'::jsonb,
   false,null,'2026-08-13','confirmed-operator-rule-2026-08-13',
   'Ikan/dori dibayar satu hari setelah distribusi.'),
  ('RUMAH_DUTA_PANGAN','CEMPLANG','IKAN',null,
   'VENDOR_PAYABLE','{"payment_window":"H_PLUS_1_AFTER_DISTRIBUTION","invoice_reconcile":true}'::jsonb,
   false,null,'2026-08-13','confirmed-operator-rule-2026-08-13',
   'Ikan/dori dibayar satu hari setelah distribusi.'),
  ('HAJI_BADRI','CEMPLANG','TAHU',null,
   'VENDOR_PAYABLE','{"payment_window":"DISTRIBUTION_DAY_AFTER_DISTRIBUTION","invoice_reconcile":true,"reject_deduction":true,"payment_flow":"HOLIL_STYLE"}'::jsonb,
   false,null,'2026-08-13','confirmed-operator-rule-2026-08-13',
   'Tahu Cemplang Haji Badri: external vendor flow; bayar hari distribusi setelah distribusi berdasarkan invoice/reject/netto.')
on conflict do nothing;
