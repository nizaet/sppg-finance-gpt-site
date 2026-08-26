-- MAJA tempe is ordered two days before cooking.  This is a dedicated rule:
-- it must not inherit either Tahu H-1 or a generic Koperasi/dry-goods rule.

update vendor_rules
set lead_time_days_before_cooking=2,
    notes=concat_ws(' | ', nullif(notes,''), 'Confirmed 2026-08-26: Tempe MAJA H-2 before cooking')
where upper(vendor_code)='KOPERASI'
  and upper(site_code)='MAJA'
  and upper(category_code)='TEMPE'
  and effective_from <= date '2026-08-26'
  and (effective_to is null or effective_to >= date '2026-08-26');
