# LPDH document-first workflow

## Operator-confirmed rules (2026-10-05)

Source: the operator's instructions in the current Codex conversation. The privately supplied `Invoice insentif 05 Oktober.pdf` is a layout reference, not authority for a new transaction amount or recipient classification.

- Active school and Posyandu records own recipient targets. School small/large student counts and school staff counts remain distinct. Staff always contributes to the large-portion PTK group. Display the ten group aggregates and the overall total without adding legacy workbook fallback totals again.
- New daily drafts start distribution and received counts from those targets. BNBA starts as `Ya`, organoleptic portions as 3, and retained samples as 2. These are editable starting values, not evidence that distribution happened or that supporting documents were uploaded. Preserve operator corrections, including zero, and historical daily snapshots.
- Select items and create invoices in LPDH first. Only active FINAL invoices for the same kitchen and service date supply new daily raw-material and operational expenses. Several invoices per day remain separately identifiable even when their items are grouped into workbook categories.
- Daily wages and incentives use separate new document packages for volunteers, teachers, and Posyandu cadres. Each package has one aggregate cover and a complete recipient appendix starting on the next page. The printed package total must equal the appendix detail total.
- One new aggregate package is one evidence document in the register, while payment calculations retain each recipient row. Shared receipt numbers are valid only within their identified aggregate source package. Historical individual receipts retain their existing numbering and meaning.
- Uploaded sender stamp and signature partially overlap in printed documents. Private artwork and banking information must not be copied into public source assets or this wiki.
- Finalization and cancellation follow the existing document lifecycle and private Drive archive. Cancellation must not produce duplicate expenses or reuse a canceled number. Document finalization does not execute a bank payment or approve a BGN maker.

## Current-form review and production reconciliation

The operator reported saved Posyandu targets appearing in the daily form but not in the cached workbook review (2026-10-05 screenshots). Saving/reloading the detailed master must refresh draft targets and their review while preserving explicit actual counts and generated historical snapshots. Navigating to Review computes the current daily form, including unsaved BNBA/distribution changes, through a read-only server calculation. It must not silently save a daily state, allocate a number, finalize a document, or create a payment. Generate continues to use the explicitly saved daily state.

Production balances as distribution POP + organoleptic + retained sample + not distributed + buffer. Show that breakdown beside the stored/input production total. Recalculation is an explicit, confirmed form edit; it is not an automatic rewrite of historical quantities and does not save until the operator saves the draft. Blank defaults remain governed by the rules above. BNBA must visibly distinguish Ya, Tidak and unselected.

## Preservation boundaries

Do not silently rewrite historical FINAL documents, generated workbook snapshots, manual legacy records, actual payments, signatures, or proof links. A template/default is not a verified financial event. Missing Posyandu detail remains missing rather than receiving an invented allocation.

This LPDH flow supplements the existing [accountant workflow](accountant-workflow.md). It does not change [BGN approval](bgn-workflow.md), [cost/claim price separation](costing.md), or internal settlements.
