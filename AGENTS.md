# AGENTS.md — SPPG Core / LLM Wiki v0

## Purpose
This repository contains both the SPPG application and the persistent SPPG knowledge layer. The knowledge layer is maintained as versioned Markdown and structured configuration.

## Upstream pattern compatibility
This SPPG implementation is an adaptation of Andrej Karpathy's "LLM Wiki" pattern, not a reduced replacement. Preserve the core capabilities of that pattern as first-class requirements:
- Raw sources are immutable and are never silently rewritten by the LLM.
- The LLM owns and maintains the wiki layer: it creates pages, updates existing pages, maintains cross-references, and integrates new evidence into prior synthesis.
- Every ingest may update multiple related wiki pages, not only create a source summary.
- New evidence must strengthen, revise, supersede, or contradict existing claims explicitly; contradictions must be recorded rather than flattened away.
- `wiki/index.md` is content-oriented navigation and must be updated on every meaningful ingest.
- `wiki/log.md` is append-only chronological history of ingests, queries filed back into the wiki, lint passes, corrections, and important maintenance operations.
- Query results that create durable operational knowledge may be filed back into the wiki so knowledge compounds instead of disappearing in chat history.
- Periodic linting must look for contradictions, stale claims, superseded claims, orphan pages, missing inbound/outbound links, concepts that deserve their own pages, and unresolved data gaps.
- Cross-links between people, suppliers, sites, workflows, concepts, and evidence-backed rules are part of the knowledge model, not decoration.
- The schema/instructions in this file must co-evolve with the wiki as the domain becomes clearer.

## Required wiki operations
### Ingest
For each new source or source batch:
1. identify the source and preserve its evidence reference;
2. extract facts, events, actors, relationships, rules, and uncertainties;
3. compare them against existing wiki knowledge;
4. update all affected entity/topic/workflow pages;
5. add or repair cross-references;
6. update `wiki/index.md`;
7. append an entry to `wiki/log.md`;
8. flag contradictions, superseded facts, and unresolved questions;
9. do not promote uncertain transactional facts to final ledger state without stronger evidence or operator confirmation.

### Query
When answering durable SPPG questions:
1. read `wiki/index.md` first;
2. inspect the most relevant pages and evidence references;
3. synthesize across pages rather than relying on a single file;
4. if the result adds durable knowledge, propose or make an appropriate wiki update and log it.

### Lint
Periodically check:
- contradictions between pages;
- stale or superseded claims;
- orphan pages;
- broken or missing cross-links;
- duplicate entity pages or aliases;
- missing source/evidence references for important claims;
- unresolved conflicts and data gaps;
- pages whose summaries no longer match their supporting details.

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
