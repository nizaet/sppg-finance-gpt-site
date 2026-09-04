-- Operator correction trail for open vendor payables.
alter table vendor_invoices
  add column if not exists correction_note text;
