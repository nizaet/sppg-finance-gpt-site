-- SPPG Core domain schema v0.5
-- Append/version historical quantities and prices; do not overwrite semantics.

create table if not exists production_cycles (
  id bigserial primary key,
  cycle_code text not null unique,
  site text not null,
  distribution_date date not null,
  cooking_at timestamptz,
  status text not null default 'PLANNING',
  created_at timestamptz not null default now()
);

create table if not exists purchase_orders (
  id bigserial primary key,
  po_code text not null,
  revision_no integer not null default 1,
  production_cycle_id bigint references production_cycles(id),
  site text not null,
  vendor_code text not null,
  status text not null default 'DRAFT',
  sent_at timestamptz,
  acknowledged_at timestamptz,
  supersedes_po_id bigint references purchase_orders(id),
  created_at timestamptz not null default now(),
  unique(po_code, revision_no)
);

create table if not exists purchase_order_items (
  id bigserial primary key,
  purchase_order_id bigint not null references purchase_orders(id),
  item_code text,
  item_name text not null,
  planned_qty numeric(18,4),
  po_qty numeric(18,4),
  unit text,
  planning_price numeric(18,2),
  po_price numeric(18,2),
  notes text
);

create table if not exists goods_receipts (
  id bigserial primary key,
  purchase_order_id bigint references purchase_orders(id),
  receipt_code text,
  received_at timestamptz,
  source_event_id bigint references candidate_events(id),
  created_at timestamptz not null default now()
);

create table if not exists goods_receipt_items (
  id bigserial primary key,
  goods_receipt_id bigint not null references goods_receipts(id),
  purchase_order_item_id bigint references purchase_order_items(id),
  received_qty numeric(18,4),
  rejected_qty numeric(18,4) default 0,
  accepted_qty numeric(18,4),
  unit text,
  quality_status text,
  notes text
);

create table if not exists vendor_invoices (
  id bigserial primary key,
  vendor_code text not null,
  site text not null,
  production_cycle_id bigint references production_cycles(id),
  invoice_number text,
  invoice_date date,
  gross_amount numeric(18,2),
  reject_deduction numeric(18,2) default 0,
  net_amount numeric(18,2),
  evidence_uri text,
  created_at timestamptz not null default now()
);

create table if not exists vendor_invoice_items (
  id bigserial primary key,
  vendor_invoice_id bigint not null references vendor_invoices(id),
  item_code text,
  item_name text not null,
  invoiced_qty numeric(18,4),
  unit text,
  vendor_cost_price numeric(18,2),
  line_total numeric(18,2)
);

create table if not exists vendor_payments (
  id bigserial primary key,
  vendor_invoice_id bigint references vendor_invoices(id),
  vendor_code text not null,
  site text,
  amount numeric(18,2) not null,
  payment_status text not null default 'PENDING',
  payment_source text,
  paid_at timestamptz,
  evidence_uri text,
  source_event_id bigint references candidate_events(id),
  created_at timestamptz not null default now()
);

create table if not exists inventory_movements (
  id bigserial primary key,
  movement_type text not null,
  item_code text,
  item_name text not null,
  qty numeric(18,4) not null,
  unit text,
  from_location text,
  to_location text,
  production_cycle_id bigint references production_cycles(id),
  source_event_id bigint references candidate_events(id),
  occurred_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists actual_usage (
  id bigserial primary key,
  production_cycle_id bigint not null references production_cycles(id),
  item_code text,
  item_name text not null,
  actual_used_qty numeric(18,4) not null,
  unit text,
  vendor_cost_price numeric(18,2),
  claim_price numeric(18,2),
  created_at timestamptz not null default now()
);

create table if not exists internal_reimbursements (
  id bigserial primary key,
  site text,
  payee_code text,
  category text,
  amount numeric(18,2) not null,
  status text not null default 'PENDING',
  incurred_at timestamptz,
  reimbursed_at timestamptz,
  evidence_uri text,
  source_event_id bigint references candidate_events(id),
  created_at timestamptz not null default now()
);

create table if not exists accountant_submissions (
  id bigserial primary key,
  production_cycle_id bigint references production_cycles(id),
  site text not null,
  accountant_code text not null,
  excel_evidence_uri text,
  sent_at timestamptz,
  status text not null default 'PENDING',
  created_at timestamptz not null default now()
);

create table if not exists accountant_invoices (
  id bigserial primary key,
  accountant_submission_id bigint references accountant_submissions(id),
  invoice_number text,
  invoice_amount numeric(18,2),
  invoice_evidence_uri text,
  received_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists bgn_makers (
  id bigserial primary key,
  production_cycle_id bigint references production_cycles(id),
  site text not null,
  reference_number text,
  amount numeric(18,2),
  status text not null default 'CREATED',
  created_at timestamptz not null default now()
);

create table if not exists bgn_approvals (
  id bigserial primary key,
  bgn_maker_id bigint not null references bgn_makers(id),
  approver_code text not null,
  status text not null default 'PENDING',
  requested_at timestamptz,
  approved_at timestamptz,
  rejected_at timestamptz,
  source_event_id bigint references candidate_events(id),
  created_at timestamptz not null default now()
);

create table if not exists bgn_receipts (
  id bigserial primary key,
  bgn_maker_id bigint references bgn_makers(id),
  destination_account_type text,
  amount numeric(18,2) not null,
  received_at timestamptz,
  evidence_uri text,
  created_at timestamptz not null default now()
);

create table if not exists settlements (
  id bigserial primary key,
  from_account_type text not null,
  to_account_type text not null,
  amount numeric(18,2) not null,
  settled_at timestamptz,
  evidence_uri text,
  production_cycle_id bigint references production_cycles(id),
  created_at timestamptz not null default now()
);
