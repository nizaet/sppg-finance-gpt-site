-- PO reminder review resolution v0.28
-- CHECKED means ordering was already completed and the operator reviewed the
-- remaining planning/stock difference. It creates neither stock nor a new PO.

alter table po_reminder_overrides
  drop constraint if exists po_reminder_overrides_resolution_check;

alter table po_reminder_overrides
  add constraint po_reminder_overrides_resolution_check
  check (resolution in ('SUFFICIENT','MANUAL_PO','CHECKED'));
