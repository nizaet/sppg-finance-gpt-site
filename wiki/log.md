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

## 2026-10-06 - Guard initial numbering against unrelated archive timestamps

- Finalization/archive retries update a document's general updated_at even when its number is unchanged. Added a bounded upgrade correction that initializes untouched bootstrap anchors from the latest retained number claim matching the current document/day number, not the latest upload attempt.
- Preserve all serial claims, document numbers, historical financial data, and operator anchors saved after the first upgrade. Originally backfilled claims use document creation/service date only to break timestamp ties; missing pre-claim edit history is not invented. Added a migration guard regression and clarified the [LPDH workflow](accounting/lpdh-document-workflow.md).

## 2026-10-06 - Operator-requested tabbed LPDH forms and mobile typed searches

- The operator requested top tabs in Master Data and Data Harian, usable folded/unfolded phone layouts without horizontal input scrolling, and typed searches for large volunteer/item lists and operational invoice item selection in addition to dropdowns.
- Keep unsaved parent form state across section switches and save all categories. Add responsive labelled input cards, wrapping tab/navigation buttons and scoped LPDH invoice/receipt cards; retain desktop columns and existing Operations layout.
- Preserve original row indexes under searches. Filtering is display-only, not a reduction in finalization/save payloads or totals. FINAL-source financial inputs remain disabled while search is usable outside the lock. Update the [LPDH workflow](accounting/lpdh-document-workflow.md) and index; use synthetic/offline acceptance without changing production transactions.

## 2026-10-18 - Actual arrival quantities and corrections after confirmation

- Operator requested actual quantities per received item and correction after an accidental OK. Added quantity entry alongside the existing exact-as-PO shortcuts and receipt editing in the PO panel and receiving history.
- Preserve PO/raw evidence/invoice/payment layers, append before/after audit records, apply only accepted-quantity stock deltas at the original effective time, and flag linked invoices for review. Newer physical SO remains the stock anchor.
- Add request idempotency, PO/receipt locking, stale snapshot checks, decimal/reject validation and synthetic SQL/UI regressions. Document the [receiving correction workflow](inventory/goods-receipt-corrections.md) and update navigation; no production transaction is changed as a test.

## 2026-10-20 - Persist PO stock edits and recognize confirmed warehouse aliases

- Operator reported that changing warehouse stock in a pulled PO did not update Gudang or purchase qty, and that Jeruk/Jeruk Medan names failed to match in both directions. The production JSX transform injected a browser-only override and retained earlier manual purchase qty.
- Add explicit audited PO-screen physical-stock save, server projection reload, forced affected-ingredient purchase recalculation, unchanged unrelated edits, and stale/duplicate/site/plan guards. Block PO creation until pending edits and projection refresh are resolved.
- The PO count explicitly precedes today's cooking; narrow the former general after-cooking recount rule for this workflow only. Keep stock facts, SO, planning, saved PO and invoice layers separate. Derive cooking dates in Jakarta.
- Carry confirmed master aliases into PO matching, allocate each physical identity once, and recognize the operator's Jeruk/Jeruk Medan shorthand while preserving distinct citrus ingredients. Add backend and production-transform UI regressions without changing production transactions as tests. Update [stock scope](inventory/po-reminder-stock-scope.md) and navigation.

## 2026-10-21 - Pantry brand equivalence and strict saved-PO ingredient identity

- Operator reported white sugar SO missing under Gula Pasir Gulaku and suspected Kaldu Jamur/Garam/Saus Tiram PO misclassification. Scoped read-only inspection confirms actual Kaldu Jamur Totole, Garam, Kecap Asin and Saus Tiram lines in MAJA KOPERASI PO #457; the kaldu badge is valid, while brand differences caused missed coverage for the other pantry lines.
- Recognize confirmed Gula/Gula Putih/Gula Pasir equivalence, ignore known pantry brand suffixes in date/unit-compatible PO matching, and retain prior cooking depletion and physical-stock allocation. Protect distinct sugar types, mushroom/seasoning/sauce types, stale IDs/aliases, canceled orders and zero-quantity PO lines.
- Keep unspecified bungkus-to-pack conversion unresolved rather than inventing package contents. No production SO, receiving, PO quantity or financial record is changed for testing. Add shared frontend/backend identity fixtures and regressions; update [stock scope](inventory/po-reminder-stock-scope.md) and navigation.

## 2026-10-23 - Cache repeated canonical master type work after measured regression

- Operator reported that the latest deployment made pulling PO and saving Gudang much slower than the two preceding releases. Read-only HTTP history confirms long inventory projection reloads while manual adjustment writes remain short. Deployment region and repository build/start configuration are unchanged across the compared revisions.
- A same-process synthetic comparison reproduces the regression in the new canonical guard: every input recomputes every master's type. Memoize master types within the request's DB snapshot, preserve all identity/ambiguity/stock rules, and avoid global or physical-stock caches.
- Add a scaling regression asserting additive rather than multiplicative taxonomy resolutions and fresh caches across snapshots. Update [stock scope](inventory/po-reminder-stock-scope.md) and navigation. Validate without creating production stock movements.
