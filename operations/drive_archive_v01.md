# Google Drive Evidence Archive v0.1

## Purpose
Google Drive stores immutable operational evidence and exchange files. It is not the transactional ledger and must not be treated as the source of truth for balances, quantities, or workflow state.

Truth order remains:
1. PostgreSQL transactional records.
2. Raw evidence / documents in Google Drive.
3. LLM Wiki operational knowledge.

## Folder structure
The active archive is organized as:

- `01_RAW_CHAT_WHATSAPP` — exported WhatsApp/chat source files and copied raw source material.
- `02_PO_VENDOR` — PO images/files, vendor order evidence, PO revisions, availability/substitution evidence.
- `03_INVOICE_AKUNTAN` — accountant Excel files, invoices, invoice-number evidence, reconciliation files.
- `04_APPROVER_BGN` — maker/approver lists and approval evidence. A sent list is not proof of approval.
- `05_KOPERASI_STOK` — Koperasi/Indogrosir stock, dispatch, transfer, and replenishment evidence.
- `06_REVIEW_PARSED_EXPORT` — parser exports, review artifacts, correction exports, reconciliation snapshots.
- `99_BACKUP` — periodic archive/backup packages.

## Environment mapping
Do not commit the real Google Drive folder IDs to this public repository. Deployment configuration may provide:

- `SPPG_DRIVE_ROOT_FOLDER_ID`
- `SPPG_DRIVE_RAW_CHAT_FOLDER_ID`
- `SPPG_DRIVE_PO_VENDOR_FOLDER_ID`
- `SPPG_DRIVE_ACCOUNTANT_FOLDER_ID`
- `SPPG_DRIVE_BGN_APPROVER_FOLDER_ID`
- `SPPG_DRIVE_KOPERASI_STOCK_FOLDER_ID`
- `SPPG_DRIVE_REVIEW_EXPORT_FOLDER_ID`
- `SPPG_DRIVE_BACKUP_FOLDER_ID`

## Ingest rule
Every evidence ingest should preserve at least:
- source type;
- external/source identifier when available;
- Drive URI or provider reference;
- content hash/idempotency key where available;
- actor/counterparty;
- site context;
- parser version;
- raw text or immutable file reference.

Parsed facts must enter staging/review before they can alter transactional workflow state. High-confidence parsing is not equivalent to financial finality.
