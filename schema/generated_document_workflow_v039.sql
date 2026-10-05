-- Additive document metadata, idempotent draft creation, and daily import audit.
alter table generated_accountant_documents add column if not exists request_key text;
alter table generated_accountant_documents add column if not exists request_hash text;
alter table generated_accountant_documents add column if not exists finalized_at timestamptz;
alter table generated_accountant_documents add column if not exists finalized_by text;
alter table generated_accountant_document_items add column if not exists item_payload jsonb not null default '{}'::jsonb;
create unique index if not exists idx_generated_docs_request_key
  on generated_accountant_documents(request_key) where request_key is not null;
