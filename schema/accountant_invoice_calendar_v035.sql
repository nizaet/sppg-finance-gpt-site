-- Canonical invoice dates for the unified Accountant/BGN calendar.
-- Existing invoice files remain in place; only missing business dates are filled.

update accountant_invoices i
set invoice_date = coalesce(i.invoice_date, s.source_distribution_date, i.received_at::date, i.created_at::date),
    site = coalesce(i.site, s.site),
    invoice_category = coalesce(i.invoice_category, 'BAHAN_BAKU'),
    updated_at = now()
from accountant_submissions s
where s.id=i.accountant_submission_id
  and (i.invoice_date is null or i.site is null or i.invoice_category is null);

update accountant_invoices
set invoice_date=coalesce(invoice_date,received_at::date,created_at::date),
    invoice_category=coalesce(invoice_category,'OPERASIONAL_LAIN'),
    updated_at=now()
where invoice_date is null or invoice_category is null;

