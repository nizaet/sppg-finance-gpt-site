-- PO reminder review resolution v0.28
-- CHECKED means the ordering task was already completed and the operator has
-- reviewed/accepted the residual difference. It does not imply extra stock or
-- create a purchase order.

alter table po_reminder_overrides
  drop constraint if exists po_reminder_overrides_resolution_check;

alter table po_reminder_overrides
  add constraint po_reminder_overrides_resolution_check
  check (resolution in ('SUFFICIENT','MANUAL_PO','CHECKED'));
