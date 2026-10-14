alter table lpdh_delivery_profiles drop constraint if exists lpdh_delivery_profiles_kind_check;
alter table lpdh_delivery_profiles add constraint lpdh_delivery_profiles_kind_check
  check(kind in ('PO','SJ','CKL','KUI','KUI_MITRA'));
