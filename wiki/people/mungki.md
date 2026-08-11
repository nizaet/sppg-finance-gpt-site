# Mungki

Role: admin/perantara Koperasi, procurement intermediary, dan internal stock fulfillment untuk Maja/Cemplang.

## Observed operational patterns
- Menerima instruksi order telur, tahu/tempe, dan kebutuhan bahan tertentu melalui WhatsApp, sering disertai gambar PO.
- Mengatur/konfirmasi kiriman bahan ke Maja dan Cemplang.
- Bahan kering dari Indogrosir masuk ke Koperasi lalu dialokasikan/dikirim ke dapur; pengiriman ini adalah internal stock transfer, bukan pembelian baru di dapur.
- Mungki sering memberi informasi stok Koperasi dan sisa stok dapur sebelum keputusan tambahan barang.
- Tambahan bahan setelah PO/menu dapat terjadi dan harus dicatat sebagai adjustment/additional fulfillment, bukan overwrite histori PO awal.
- Kekurangan, reject, atau ketidaksesuaian qty perlu direkonsiliasi dengan penerimaan aktual.
- Tempe/tahu Maja dan telur via Mungki mengikuti cash purchase/internal reimbursement flow sesuai rule operator.

## Event candidates
PROCUREMENT_REQUEST
PROCUREMENT_REQUEST_REVISION
KOPERASI_STOCK_CHECK
KOPERASI_STOCK_AVAILABLE
INTERNAL_STOCK_TRANSFER_REQUEST
INTERNAL_STOCK_TRANSFER_DISPATCHED
KITCHEN_STOCK_RECEIVED
ADDITIONAL_MATERIAL_REQUEST
RECEIVED_QTY_MISMATCH
QUALITY_REJECT_REPORTED
CASH_PURCHASE_RECORDED
INTERNAL_REIMBURSEMENT_PENDING

## Evidence / provenance
Primary source: Google Drive file `WhatsApp Chat with Mungkie 2.txt` (Drive file id: 1qPJD-wzTawsr0HQ3s7qA4OYfnb0qlstg).

Observed examples in Aug 2026 include telur Maja/Cemplang, tempe Cemplang, tahu Maja, stock queries from Koperasi, Indogrosir replenishment, additional mayonnaise, and reject/shortage discussions.
