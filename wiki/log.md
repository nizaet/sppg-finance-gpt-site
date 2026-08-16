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
