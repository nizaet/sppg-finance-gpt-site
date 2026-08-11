-- Initial reference seed from confirmed SPPG operating knowledge.
-- Payment terms intentionally left NULL unless supported by explicit evidence.

insert into sites(code,name) values
  ('MAJA','SPPG MAJA BARU'),
  ('CEMPLANG','SPPG CEMPLANG 2')
on conflict (code) do update set name=excluded.name, active=true;

insert into entities(code,name,entity_type,metadata) values
  ('HOLIL','Holil','VENDOR','{"categories":["SAYUR","BUAH"]}'::jsonb),
  ('MUNGKI','Mungki','PERSON','{"functions":["KOPERASI_ADMIN","PROCUREMENT_INTERMEDIARY","STOCK_FULFILLMENT"]}'::jsonb),
  ('WIKIAN','Wikian','VENDOR','{"categories":["AYAM"]}'::jsonb),
  ('RUMAH_DUTA_PANGAN','Rumah Duta Pangan','VENDOR','{"categories":["IKAN"]}'::jsonb),
  ('HERU','Heru','VENDOR','{"categories":["GAS"]}'::jsonb),
  ('DEDE','Dede','VENDOR','{"categories":["BERAS"]}'::jsonb),
  ('HAJI_BADRI','Haji Badri','VENDOR','{"categories":["TAHU"]}'::jsonb),
  ('INDOGROSIR','Indogrosir','VENDOR','{"categories":["BAHAN_KERING"]}'::jsonb),
  ('KOPERASI','Koperasi','INTERNAL_ORG','{"function":"INTERNAL_INVENTORY"}'::jsonb),
  ('TIARA','Tiara','PERSON','{}'::jsonb),
  ('UYA','Uya','PERSON','{}'::jsonb),
  ('EMBUN','Embun','PERSON','{}'::jsonb),
  ('MALIK','Malik','PERSON','{}'::jsonb)
on conflict (code) do update set name=excluded.name, entity_type=excluded.entity_type, metadata=excluded.metadata, active=true;

insert into entity_site_roles(entity_code,site_code,role_code,effective_from) values
  ('TIARA','MAJA','ACCOUNTANT','2026-01-01'),
  ('UYA','CEMPLANG','ACCOUNTANT','2026-01-01'),
  ('EMBUN','MAJA','KITCHEN_HEAD_APPROVER','2026-01-01'),
  ('MALIK','CEMPLANG','KITCHEN_HEAD_APPROVER','2026-01-01'),
  ('MUNGKI','MAJA','KOPERASI_ADMIN','2026-01-01'),
  ('MUNGKI','CEMPLANG','KOPERASI_ADMIN','2026-01-01')
on conflict do nothing;

-- Lead time anchored to cooking time.
insert into vendor_rules(vendor_code,site_code,category_code,lead_time_days_before_cooking,effective_from,evidence_ref,notes) values
  ('HOLIL','MAJA','SAYUR_BUAH',1,'2026-01-01','confirmed-operator-rule','H-1 before cooking'),
  ('HOLIL','CEMPLANG','SAYUR_BUAH',1,'2026-01-01','confirmed-operator-rule','H-1 before cooking'),
  ('WIKIAN','MAJA','AYAM',3,'2026-01-01','confirmed-operator-rule','H-3 before cooking'),
  ('WIKIAN','CEMPLANG','AYAM',3,'2026-01-01','confirmed-operator-rule','H-3 before cooking')
on conflict do nothing;

-- Mungki-mediated cash reimbursement flows. Upstream vendors remain distinct from intermediary.
insert into vendor_rules(vendor_code,site_code,category_code,lead_time_days_before_cooking,internal_reimbursement,intermediary_code,effective_from,evidence_ref,notes) values
  ('KOPERASI','MAJA','TEMPE_TAHU_CASH_FLOW',2,true,'MUNGKI','2026-01-01','confirmed-operator-rule','Tempe/tahu Maja via Mungki; internal month-end reimbursement'),
  ('KOPERASI','MAJA','TELUR_CASH_FLOW',null,true,'MUNGKI','2026-01-01','confirmed-operator-rule','Eggs via Mungki; internal month-end reimbursement'),
  ('KOPERASI','CEMPLANG','TELUR_CASH_FLOW',null,true,'MUNGKI','2026-01-01','confirmed-operator-rule','Eggs via Mungki; internal month-end reimbursement')
on conflict do nothing;
