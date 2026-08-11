# AGENTS.md — SPPG Core / LLM Wiki v0

## Purpose
This repository contains both the SPPG application and the persistent SPPG knowledge layer. The knowledge layer is maintained as versioned Markdown and structured configuration.

## Truth hierarchy
1. PostgreSQL transactional records = source of truth for amounts, quantities, balances, and workflow status.
2. Raw evidence in Google Drive = source documents/evidence (WhatsApp exports, PO images, vendor invoices, accountant Excel, accountant invoices, payment proofs).
3. LLM Wiki = rules, patterns, mappings, decisions, and operational knowledge; it is not the accounting ledger.
4. LLM output must never invent transaction amounts or mark a financial event final without evidence or explicit operator input.

## Historical integrity
Never overwrite historical quantity/price layers. Keep planned_qty, po_qty, received_qty, actual_used_qty, planning_price, po_price, vendor_cost_price, and claim_price distinct.

## Procurement rules
- PO may be sent to a vendor as an image; structured PO data must still exist in the database.
- Procurement lead time is anchored to cooking time, not distribution time.
- Known initial lead times: vegetables/fruit H-1 before cooking, tempe H-2, chicken H-3.
- Vendor payment cadence is configurable per vendor; do not infer daily/weekly terms unless supported by evidence.

## Inventory rules
- Dry goods flow: Indogrosir -> Koperasi -> Mungki -> Maja/Cemplang.
- Dispatch from Koperasi to a kitchen is INTERNAL_STOCK_TRANSFER, not a new purchase expense.

## Reimbursement rules
- Tempe/tahu Maja via Mungki: paid from cash, reimbursed internally at month end.
- Eggs via Mungki: paid from cash, reimbursed internally at month end.
- Internal cash reimbursement is separate from BGN reimbursement.
- Yayasan/Koperasi -> BCA Operational is an inter-account settlement, not a new expense.

## Current role mapping
- Tiara = accountant, Maja.
- Uya = accountant, Cemplang.
- Embun = kitchen head / BGN approver, Maja.
- Malik = kitchen head / BGN approver, Cemplang.
- Wikian = chicken vendor only.
- Holil = vegetables & fruit vendor.
- Mungki = Koperasi admin / procurement intermediary / stock fulfillment.

## Conflict handling
If chat, database, and documents conflict, preserve all evidence, flag the conflict, and do not silently choose one value. Prefer stronger source evidence and request operator confirmation only when the conflict cannot be resolved deterministically.
