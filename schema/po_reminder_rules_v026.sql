-- PO reminder procurement-rule normalization v0.26
-- Effective 2026-08-16 based on operator-confirmed site-specific rules.
--
-- Maja: Tempe is KOPERASI H-4 and must not inherit Tahu lead time.
-- Tahu keeps the previously confirmed H-2 from the legacy combined rule.
-- Cemplang: Tempe vendor is KOPERASI, but its lead time is intentionally NULL
-- until the operator configures the dedicated value. Do not infer it from Tahu
-- or generic Koperasi/dry-goods rules.

update vendor_rules
set effective_to = date '2026-08-15',
    notes = concat_ws(' | ', nullif(notes,''), 'Superseded by separate TEMPE and TAHU rules effective 2026-08-16')
where vendor_code = 'KOPERASI'
  and site_code = 'MAJA'
  and category_code = 'TEMPE_TAHU_CASH_FLOW'
  and effective_from <= date '2026-08-15'
  and (effective_to is null or effective_to >= date '2026-08-16');

insert into vendor_rules(
  vendor_code, site_code, category_code, lead_time_days_before_cooking,
  internal_reimbursement, intermediary_code, effective_from, effective_to,
  evidence_ref, notes
) values
  (
    'KOPERASI','MAJA','TEMPE',4,
    true,'MUNGKI',date '2026-08-16',null,
    'confirmed-operator-rule-2026-08-16',
    'Tempe Maja via Koperasi/Mungki; H-4 before cooking; separate from Tahu'
  ),
  (
    'KOPERASI','MAJA','TAHU',2,
    true,'MUNGKI',date '2026-08-16',null,
    'split-from-confirmed-legacy-rule',
    'Tahu Maja separated from Tempe; preserves previously confirmed H-2 lead time'
  ),
  (
    'KOPERASI','CEMPLANG','TEMPE',null,
    false,null,date '2026-08-16',null,
    'confirmed-vendor-only-2026-08-16',
    'Tempe Cemplang vendor confirmed Koperasi; dedicated lead time not yet configured'
  )
on conflict (vendor_code, site_code, category_code, effective_from)
do update set
  lead_time_days_before_cooking = excluded.lead_time_days_before_cooking,
  internal_reimbursement = excluded.internal_reimbursement,
  intermediary_code = excluded.intermediary_code,
  effective_to = excluded.effective_to,
  evidence_ref = excluded.evidence_ref,
  notes = excluded.notes;

-- Existing active calculator snapshots may predate the corrected taxonomy and
-- therefore have no preferred vendor on Tempe rows. Backfill only ACTIVE planning
-- data; historical PO/receiving/invoice rows are deliberately untouched.
update planning_snapshot_items psi
set preferred_vendor_code = 'KOPERASI'
from planning_snapshots ps
where ps.id = psi.planning_snapshot_id
  and ps.status = 'ACTIVE'
  and upper(ps.site) in ('MAJA','CEMPLANG')
  and lower(coalesce(psi.item_name,'')) ~ '(^|[^a-z])tempe([^a-z]|$)'
  and coalesce(upper(psi.preferred_vendor_code),'') <> 'KOPERASI';
