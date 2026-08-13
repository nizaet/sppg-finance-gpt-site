# WhatsApp Parser Examples v0.3

These are generalized examples derived from real SPPG chat patterns. Raw chat remains in Google Drive; the wiki stores only extracted operational knowledge.

## Holil — PO revision
Input pattern:
`Pak ada tambahan daun bawang tambah 2kg, wortel tambahan 2kg`

Expected:
- event_type: PO_REVISION
- vendor: HOLIL
- mutation: ADD_QTY
- requires_confirmation: true

## Holil — market price update
Input pattern:
`wortel lagi sulit, harga naik`

Expected:
- event_type: PRICE_UPDATE
- secondary candidate: ITEM_UNAVAILABLE_OR_SUBSTITUTION
- do not automatically alter final PO price without operator acceptance

## Holil — reject/payment deduction
Input pattern:
`barang BS/reject ... potong pembayaran`

Expected sequence:
QUALITY_REJECT -> REJECT_QTY_RECONCILED -> PAYMENT_ADJUSTMENT_CANDIDATE

Store separately:
- gross_invoice_amount
- reject_qty
- reject_value
- net_payable_amount

## Mungki — scheduled tahu/tempe procurement
Input pattern contains:
- item
- quantity/papan/pcs
- delivery date

Expected:
- event_type: PO_NEW or PO_REVISION depending on existing order context
- intermediary: MUNGKI
- site inferred only if explicit or resolved from active production cycle

## Mungki — Koperasi stock transfer
Input pattern:
`stok gudang koperasi` + request to send dry goods to Maja/Cemplang

Expected:
- event_type: KOPERASI_STOCK_TRANSFER_REQUEST
- from: KOPERASI
- to: MAJA or CEMPLANG
- expense_created: false

## Mungki — receipt discrepancy
Input pattern:
`pesan 8 papan`, later actual quantity differs

Expected:
- preserve ordered_qty
- record received_qty separately
- create GOODS_RECEIVED_ADJUSTMENT
- never overwrite the original PO quantity

## Payment safety
A message such as `nanti saya transfer` is not proof of payment.

It is PAYMENT_INTENT / PAYMENT_PENDING.

A payment should become confirmed only with stronger evidence such as explicit completed-transfer language plus amount/reference/evidence, or bank evidence.
