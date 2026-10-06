# Knowledge Log

## 2026-08-11 — v0 initial foundation
- GitHub write access confirmed.
- Created SPPG LLM Wiki foundation on branch `llm-wiki-v0`.
- Confirmed accountant mapping: Tiara=Maja, Uya=Cemplang.
- Confirmed kitchen heads/approvers: Embun=Maja, Malik=Cemplang.
- Confirmed Wikian is chicken vendor only.
- Added initial vendor map, lead-time rules, Koperasi stock-transfer rule, internal cash reimbursement rule, accountant/BGN workflow, and WhatsApp event schema.
- Vendor registry defined as dynamic/configurable, not hard-coded.

## 2026-08-11 — WhatsApp ingest: Holil & Mungki
- Ingested extracted text source `WhatsApp Chat with Ud Holi Effendy Tanah Tinggi.txt` (Drive id `1vxSJilgBHzxUHK4NLAx6dnZPowAhE0MD`).
- Learned Holil patterns: PO revisions, price/availability changes, item substitution, reject/BS reconciliation, gross-to-net vendor payment drafts, and per-site payment separation.
- Ingested extracted text source `WhatsApp Chat with Mungkie 2.txt` (Drive id `1qPJD-wzTawsr0HQ3s7qA4OYfnb0qlstg`).
- Learned Mungki patterns: telur/tahu/tempe procurement requests, Koperasi stock checks, Indogrosir replenishment, internal stock transfers to Maja/Cemplang, additional material requests, and shortage/reject reconciliation.
- Added dedicated knowledge pages for Holil and Mungki with provenance.

## 2026-08-12 — Google Drive evidence archive initialized
- Created a dedicated `SPPG OPERASIONAL - LLM WIKI` evidence archive in Google Drive.
- Added separate folders for raw WhatsApp/chat, vendor PO evidence, accountant invoices/Excel, BGN approver evidence, Koperasi stock evidence, parsed/review exports, and backups.
- Documented archive responsibilities and ingest rules in `operations/drive_archive_v01.md`.
- Added deployment environment placeholders for Drive folder mapping without committing live folder IDs to the public repository.
- PostgreSQL remains the transactional source of truth; Drive remains the evidence/archive layer.

## 2026-08-16 — PO reminder strict coverage + Tempe split
- Corrected PO reminder semantics: a PO only covers a requirement when site, vendor, distribution date, item type, canonical unit, and quantity match. Same-vendor/latest-PO and same-send-date fallbacks are forbidden.
- Open/overdue/upcoming requirements no longer display an unrelated PO code. Partial exact coverage is tracked separately and does not mark the requirement complete.
- Preserved projected stock value `available_for_po=0` instead of incorrectly falling back to physical balance.
- Confirmed Tempe Maja vendor Koperasi with H-4 lead time, separated from Tahu. Tahu Maja preserves the prior H-2 rule after the legacy combined rule is retired.
- Confirmed Tempe Cemplang vendor Koperasi. Its dedicated lead time remains intentionally unset until configured; it must not borrow Tahu or generic Koperasi lead time.
- Added regression tests covering wrong-date SENT POs, insufficient quantities, finalized/draft states, Tempe site rules, and zero projected stock.


## 2026-09-08 — Operations navigation and automatic PO reads
- Moved owner account navigation into the Operations sidebar, including Maja/Cemplang accountant links and logout, to prevent overlap with kitchen selectors. Scoped neutral dark surfaces, consistent controls, and responsive navigation to Operations.
- Calendar reads now follow the selected month, including adjacent weeks. Reminders load automatically for the visible kitchen. Both use bounded session-memory caching (60 seconds, up to 32 keys), deduplicate in-flight reads, retain prior data on error, and reject late responses for another period/site.
- Successful operational writes invalidate the display cache. Hidden panels stop automatic polling. Explicit Calculator reconciliation remains an operator action; automatic display reads do not finalize or rewrite transactional records.
- Updated the former manual-only enhancement build assertion to match the requested automatic-read behavior. Added production-transformed React regressions for month/site races, cache refresh and failures, alongside existing navigation and draft-retention checks.


## 2026-09-09 — Calendar receipt/revision fixes and shared dark appearance
- Reset receiving panels by PO identity, reject stale detail/status responses, and guard duplicate receipt clicks. A receipt saved on a previous PO cannot reopen its popup after selecting another PO.
- Connect calendar revisions to the existing PO editor, reuse existing drafts, and serialize concurrent server revision requests with a source-row lock. Calendar cards group revisions while retaining access to previous versions; no historical PO or receipt is deleted.
- Complete screen-only dark styling for both legacy calculators and accountant pages, including calendar cells, colored notices, modal content, table states, and form controls.
- Production-transformed React tests cover receipt identity, async races, actual revision editor handoff, draft reuse and grouped cards. Backend tests check existing-draft reuse and calculator rendering/auth regressions.
- Removed a receiving-badge MutationObserver feedback loop and prefer exact rendered PO status over shared-code matching, preventing a revision from inheriting another version's badge. Added an idempotent DOM-update regression.

## 2026-09-10 — GPT settlement validation and dividend-advance boundary
- Railway runtime traces at 10:54 and 10:55 UTC show `SettlementIn` rejecting a GPT vendor/dividend payload missing `from_account_type`; the uncaught validation error returned HTTP 500 before the domain write.
- Invalid operational command payloads now return HTTP 422 with `canCommit=false` and field errors without echoing transaction data. Settlement rejects unknown allocation fields and nonpositive/nonfinite amounts; valid inter-account transfer behavior is retained.
- Action descriptions and GPT instructions explicitly distinguish inter-account transfers from accountant debt payments. Automatic dividend advance/credit allocation is not implemented by `CREATE_SETTLEMENT`; no financial record or balance was changed by this maintenance.
- Accountant UI debt edits write Firestore, whereas the finance Action list reads PostgreSQL. Conflicting payment status requires reconciliation of the same IDs rather than overwriting manual edits from stale copies.
- Added HTTP regressions for preview/commit validation, wrong-domain payloads, valid transfer dispatch and other invalid commands. Kept GPT instructions within the existing 8,000-byte gate and restored the stock-opname no-splitting description required by its regression.

## 2026-09-12 — Cemplang PO stock matching and physical correction anchors
- Operator-provided warehouse/PO excerpts show Cemplang SO #57 dated September 4 and snapshot #138 for September 14. The PO reads current balances but depletes earlier plans; garlic powder incorrectly borrowed fresh garlic stock, and coriander pcs was treated as kg. Bombay appears in the supplied warehouse table but not in the supplied PO lines.
- Both kitchens now use exact/confirmed ingredient identity and known unit conversions, counting each stock row once regardless of alias count. Unknown package-to-weight conversions are disclosed rather than assumed.
- Explicit MANUAL_STOCK_EDIT facts with target_balance provide a per-item physical check date. Plans and provisional PO supply before that local date no longer adjust the newly confirmed stock again; same-day and later plans remain, and ordinary receiving does not reset the planning baseline.
- Warehouse/PO views disclose provisional incoming PO supply and the physical correction date. Existing SO, PO, receipt and financial records are unchanged. Added production-transformed JavaScript and Python regressions for both kitchens.

## 2026-09-12 — Same-kitchen PO reminder stock check and direct warehouse additions
- PO reminders for MAJA and CEMPLANG now scope available stock to the selected kitchen. Koperasi inventory remains separate until an auditable internal transfer reaches the destination kitchen.
- A fresh reminder check may close only exact, unit-compatible stock that was not already included in the original projection. Similar names are returned as operator references with their balance, never silently treated as the same item.
- Saving a stock check records a manual inventory correction and recalculates the queue. It no longer saves a `SUFFICIENT` override that could hide an insufficient requirement.
- The Gudang screen supports adding stock from an existing master item or a new item. Categories offer the existing list while allowing a new category; master creation and stock movement are auditable and do not rewrite SO history.

## 2026-09-13 — PO reminder timeout and Fold/mobile reliability
- Railway timing evidence showed CEMPLANG reminder requests reaching 48–60 seconds. The queue was repeating the full inventory projection to prebuild stock-reference choices, and the production cooking-day projection assignment bypassed the previously installed single-flight cache.
- The main reminder request now performs only its authoritative selected-kitchen projection. Closest warehouse references are loaded once and only when **Cek stok gudang** is opened; similar names remain informational and never suppress a PO automatically.
- Restored the live exact-PO-coverage guard before any physical stock correction, which had been overwritten in the latest production tree. A stale dialog cannot change stock for an item already covered by a saved PO.
- The PO action scope is now described consistently as overdue seven days plus today and tomorrow. The UI no longer advertises or requests a misleading 21-day action horizon.
- Operations, PO Vendor, Gudang, Accountant/BGN, and legacy Calculator layouts received Fold/mobile containment rules: one-column forms, wrapping actions, viewport-safe modals, and explicit touch scrolling for wide tables, calendars, tabs, and navigation controls.
- No planning, PO, receipt, stock, or financial transaction was changed by this maintenance.

## 2026-10-05 - LPDH aggregate targets and daily document packages

- The operator requested detailed active school/Posyandu targets as the authoritative group totals, including large-portion school staff/PTK, with an overall total and editable initial distribution/received values. Initial BNBA is Ya, organoleptic 3, and retained samples 2. Defaults are not proof of distribution or receipt.
- New daily expenses must come from active FINAL invoices/kuitansi for the selected site/date. Several operational invoices remain independently numbered and traceable. Historical manual rows, prior generated snapshots, and final documents are preserved.
- New daily wage/teacher/cadre packages each use one aggregate cover, one printed receipt number, and a complete recipient appendix starting on the next page. One package occupies one evidence-register entry; per-recipient calculations remain detailed. Historical individually numbered receipts keep their meaning.
- Reviewed the privately supplied incentive PDF as a layout reference. Its transaction amount, banking data, artwork, and Insentif Mitra classification are not copied into a new transaction or public documentation.
- Added the [LPDH document-first workflow](accounting/lpdh-document-workflow.md) and connected it to the existing accountant/BGN workflow. Approval, actual payments, internal settlements, and other Operations modules are outside this change.

## 2026-10-05 - LPDH current-form review and layout correction

- The operator's three screenshots demonstrated Posyandu values present in the daily form but zero in a stale review, a retained old production value, clipped BNBA text, and tables overflowing cards. The operator approved the scoped correction and production deployment; the screenshots remain private source evidence, not public repository assets.
- Added a read-only current-form preview calculation and master-save refresh. Explicit actual values, financial source provenance and historical generated snapshots remain protected; review does not write financial/daily state or claim numbers.
- Documented the production balance and an explicit confirmed recalculation instead of silently rewriting saved quantities. Widened BNBA controls and contained wide tables within fieldsets/cards.
- Updated the [LPDH workflow](accounting/lpdh-document-workflow.md), [accountant workflow](accounting/accountant-workflow.md) and index. Other Operations, procurement, approval, settlement and payment workflows remain outside scope.

## 2026-10-05 - LPDH template, common evidence and confirmed wage reconciliation

- The operator reported a failed official-template upload, repeated proof fields and a blocked aggregate wage draft, and requested column-by-column comparison with the private accountant workbook.
- Corrected the JSON upload contract, isolated template metadata writes and prevented filled template inputs from carrying prior financial or BAST evidence into a new output. Master import remains a separate workflow.
- Shared proof/reference edits apply to every identified invoice/package source row, without modifying its financial values. Added a per-line workbook appendix while retaining official financial-sheet layout.
- Added explicit snapshot-bound confirmation before replacing overlapping historical manual payment inputs with a FINAL aggregate package. Exact prior rows remain archived server-side; other subtypes, FINAL records and generated days remain protected.
- Aligned D_Insentif calculation with its official eligibility gate. Documented BAST requirements and distinguished calculated entitlement from authentic PPK/payment evidence. Private source/app differences were recorded without overwriting live data. Other Operations modules and actual bank payment execution remain outside scope.

## 2026-10-06 - Operator-authorized server template and fill-only Excel downloads

- The operator requested that downloads copy a stored Excel template and fill yellow inputs while retaining formulas, then explicitly authorized one-time preparation of a server copy. Future template upload must remain supported; mapping changes require joint adjustment, not silent substitutions.
- Added private original/prepared template separation, source hashes and prior-version retention on atomic replacement. The original workbook is immutable and never a public repository asset. New/unmapped input cells and shifted headers are rejected before installation.
- Prepared document-level register slots once for shared aggregate invoice/receipt numbers. The stored template includes a source-row appendix and retained financial formulas. Download patches input values only, preserving non-input cells and non-worksheet ZIP parts; missing/corrupt templates block instead of invoking a rebuilt fallback.
- Added synthetic formula/array-formula, style, mapping, capacity, literal-text, shared-reference and cached-template regressions. Read-only acceptance with the private accountant workbook verifies original immutability and formula/style preservation; native Excel recalculation remains an operator/open-in-Excel check.
- Updated the [LPDH workflow](accounting/lpdh-document-workflow.md) and index. No actual receipt, payment, generated historical daily state or unrelated Operations workflow was changed.

## 2026-10-06 - Operator-authorized routine drafts, last-saved numbers and PDF/Excel invoice pairs

- The operator requested previous-service-day routine reuse, continuation from the latest operator-saved invoice number, and paired PDF/Excel archives grouped by document date; explicitly authorized implementation and production deployment with GPT-6.1 Sol High.
- Added allowlisted routine copies, separately editable operational invoice queues and teacher/cadre packages, current-master daily volunteers, current-master targets, and confirmed PM draft reuse. Old payment/BAST evidence, statements, acceptance signatures and FINAL status do not transfer. Generated snapshots and concurrent daily changes are protected.
- Added last-saved number anchors, collision skipping and persistent canceled-number claims, without resetting suffixes or counters. Existing numbering lacks a dedicated edit timestamp; upgrade uses last saved record once, and subsequent explicit number saves take precedence.
- Added authenticated FINAL Excel exports from the same PDF snapshot, full aggregate recipient appendices, typed values/literal identifiers, private artwork, paired site/year/month/date Drive folders, stable artifact keys, complete/partial statuses and missing-file retry. Old archives and existing Operations destinations remain intact.
- Added synthetic backend, UI, scope, numbering, collision, read-only copy, generated/concurrent guards, export/appendix/artwork and partial retry regressions. Verified synthetic Excel layout and build; actual production financial documents are not finalized for testing. Updated the [LPDH workflow](accounting/lpdh-document-workflow.md) and index.
