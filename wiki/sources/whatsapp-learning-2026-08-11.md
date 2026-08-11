# WhatsApp Learning Ingest — 2026-08-11

## Raw sources
- Tiara Akuntan ZIP — Google Drive file id: `15pTJAhv-XADvtg-FaplJK-TyrdFFTJy-`
- Uya Akuntan ZIP — Google Drive file id: `1ictizoO0ulnm-xDh4u8-oTZjodlYRo5J`
- Malik Abdul Aziz KA SPPG ZIP — Google Drive file id: `1jmG35KahVt_rZbeci3JFYwTBNIWMquS3`

Raw sources remain immutable. This page stores extracted durable knowledge only.

## Durable findings

### Tiara / Maja
- Tiara is the accountant for Maja.
- Early operational discussions show accountant work includes reviewing operational cost assumptions, preparing/maintaining spreadsheet calculations, handling invoice-related inputs, and supporting BGN-related administration.
- Historical chats mention BGN disbursement cadence discussions; treat these as historical observations, not permanent policy unless confirmed by current process.

### Uya / Cemplang
- Uya is the accountant for Cemplang.
- Uya maintains Cemplang-specific spreadsheet/evidence handling and stores supporting receipts/PO evidence for accounting work.
- A historical rule in chat states petty cash purchases require organized receipts and separate reporting; this is evidence of a petty-cash evidence workflow.
- Historical invoice taxonomy discussed in chat:
  - Yayasan: incentive invoice; operational Yayasan invoice.
  - Koperasi: raw-material invoice; operational-material invoice.
- This taxonomy must be validated against current SPPG process before being enforced as an immutable accounting rule.

### Malik / Cemplang approval
- Malik is the Cemplang kitchen head / approval actor.
- Recurring messages use a structured `UPDATE PENDING APPROVAL` format containing date, transaction label, internal/reference code, counterparty, and amount.
- Approval lists may include multiple maker items in one message.
- Historical chat shows maker timing can be operationally urgent, including requests to make transactions before 08:00.
- Approval state must be tracked per maker item; a later message can clarify an item was already approved earlier.
- Do not infer approval merely because a list was sent; explicit approval evidence or system status is required.

## Event patterns learned
- `ACCOUNTING_EVIDENCE_REGISTERED`
- `ACCOUNTANT_INVOICE_TAXONOMY_OBSERVED`
- `PETTY_CASH_EVIDENCE_REQUIRED`
- `MAKER_CREATED`
- `APPROVAL_LIST_SENT`
- `APPROVAL_PENDING`
- `APPROVAL_CONFIRMED`
- `APPROVAL_ALREADY_DONE`
- `MAKER_DEADLINE_REQUESTED`

## Confidence
- Role mappings: HIGH — directly confirmed by operator and chat identity.
- Malik pending-approval format: HIGH — repeatedly observed in raw chat.
- Historical invoice taxonomy: MEDIUM — observed in chat but may have evolved.
- Historical disbursement cadence / timing: LOW-MEDIUM for current policy; preserve as historical evidence only.
