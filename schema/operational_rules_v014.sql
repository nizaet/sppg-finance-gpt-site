-- SPPG operational rules v0.14
-- Effective-dated clarification from operator on 2026-08-12.
-- Preserve historical rules; close earlier overlapping rows first.

update vendor_rules
set effective_to = date '2026-08-11'
where effective_to is null
  and effective_from < date '2026-08-12'
  and (
    (vendor_code='KOPERASI' and site_code='MAJA' and category_code in ('TEMPE_TAHU_CASH_FLOW','TELUR_CASH_FLOW'))
    or (vendor_code='KOPERASI' and site_code='CEMPLANG' and category_code='TELUR_CASH_FLOW')
    or (vendor_code='WIKIAN' and site_code in ('MAJA','CEMPLANG') and category_code='AYAM')
  );

insert into vendor_rules(
  vendor_code,site_code,category_code,lead_time_days_before_cooking,
  payment_term_code,payment_term_payload,internal_reimbursement,intermediary_code,
  effective_from,evidence_ref,notes
) values
  ('KOPERASI','MAJA','TEMPE_TAHU_CASH_FLOW',2,
   'CASH_FIRST','{"payment_source":"KAS","reimburse_after_cash":true,"items":["TEMPE","TAHU"]}'::jsonb,
   true,'MUNGKI','2026-08-12','confirmed-operator-rule-2026-08-12',
   'Tempe dan tahu Maja dibayar menggunakan uang kas lebih dahulu; jangan dibuat vendor bank payable.'),
  ('KOPERASI','MAJA','TELUR_CASH_FLOW',null,
   'CASH_FIRST','{"payment_source":"KAS","reimburse_after_cash":true,"items":["TELUR"]}'::jsonb,
   true,'MUNGKI','2026-08-12','confirmed-operator-rule-2026-08-12',
   'Telur Maja dibayar menggunakan uang kas lebih dahulu.'),
  ('KOPERASI','CEMPLANG','TELUR_CASH_FLOW',null,
   'CASH_FIRST','{"payment_source":"KAS","reimburse_after_cash":true,"items":["TELUR"]}'::jsonb,
   true,'MUNGKI','2026-08-12','confirmed-operator-rule-2026-08-12',
   'Telur Cemplang dibayar menggunakan uang kas lebih dahulu.'),
  ('WIKIAN','MAJA','AYAM',3,
   'VENDOR_PAYABLE','{"order_horizon_days":2,"stock_carryover":true,"payment_window":"END_OF_WEEK"}'::jsonb,
   false,null,'2026-08-12','confirmed-operator-rule-2026-08-12',
   'Ayam biasanya dipesan untuk kebutuhan dua hari; sisa penerimaan menjadi stok untuk mengurangi kebutuhan PO berikutnya.'),
  ('WIKIAN','CEMPLANG','AYAM',3,
   'VENDOR_PAYABLE','{"order_horizon_days":2,"stock_carryover":true,"payment_window":"END_OF_WEEK"}'::jsonb,
   false,null,'2026-08-12','confirmed-operator-rule-2026-08-12',
   'Ayam biasanya dipesan untuk kebutuhan dua hari; sisa penerimaan menjadi stok untuk mengurangi kebutuhan PO berikutnya.'),
  ('HAJI_BADRI','CEMPLANG','TAHU',null,
   'VENDOR_PAYABLE','{"invoice_reconcile":true,"reject_deduction":true,"payment_flow":"HOLIL_STYLE"}'::jsonb,
   false,null,'2026-08-12','confirmed-operator-rule-2026-08-12',
   'Tahu Cemplang Haji Badri mengikuti alur Holil: PO, penerimaan/invoice, rijek, netto, pembayaran, bukti transfer.')
on conflict do nothing;
