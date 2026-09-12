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
