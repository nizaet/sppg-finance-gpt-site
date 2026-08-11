# Holil / Haji Holil

Role: vendor sayur & buah untuk SPPG Maja dan Cemplang.

## Observed operational patterns
- PO dikirim melalui WhatsApp, sering dalam bentuk gambar/daftar.
- PO dapat direvisi setelah vendor acknowledge, termasuk perubahan qty dan pergantian buah/sayur karena stok/harga pasar.
- Vendor aktif memberi info perubahan harga dan ketersediaan sebelum belanja.
- Qty final harus mengikuti revisi terakhir yang dikonfirmasi, bukan pesan awal.
- Barang reject/BS/rijek ditimbang dan dipisahkan dari qty layak.
- Reject dapat mengurangi nilai pembayaran vendor.
- Pembayaran dapat direkonsiliasi per site dan per tanggal tagihan.
- Rancangan pembayaran harus memisahkan bruto, potongan reject, dan netto.
- Reject lintas site dapat direkap bersama, tetapi nilai potongan tetap harus dialokasikan ke site/tagihan yang benar.

## Event candidates
PO_NEW
PO_REVISION
PO_ACKNOWLEDGED
VENDOR_PRICE_CHANGED
ITEM_SUBSTITUTION_PROPOSED
GOODS_RECEIVED
QUALITY_REJECT_RECORDED
REJECT_QTY_RECONCILED
VENDOR_PAYMENT_REQUESTED
VENDOR_PAYMENT_DRAFTED
VENDOR_PAYMENT_CONFIRMED

## Evidence / provenance
Primary source: Google Drive file `WhatsApp Chat with Ud Holi Effendy Tanah Tinggi.txt` (Drive file id: 1vxSJilgBHzxUHK4NLAx6dnZPowAhE0MD).

Observed examples around 8-11 Aug 2026 include PO revision of jeruk, vendor price changes, edamame/semangka reject reconciliation, and payment drafts with gross/reject/net amounts.
