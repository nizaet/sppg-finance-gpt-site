-- SPPG accountant Excel provenance v0.20
-- One generated accountant submission per site/accountant/planning snapshot.
-- Regeneration returns the existing submission instead of creating duplicate rows.

alter table accountant_submissions
  add column if not exists source_planning_snapshot_id bigint references planning_snapshots(id),
  add column if not exists generated_filename text;

create unique index if not exists uq_accountant_submission_snapshot
  on accountant_submissions(site, accountant_code, source_planning_snapshot_id)
  where source_planning_snapshot_id is not null;
