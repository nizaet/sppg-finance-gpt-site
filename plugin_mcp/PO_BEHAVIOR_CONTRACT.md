# SPPG Plugin MCP - PO Behavior Contract

## Prinsip utama
Plugin/MCP tidak boleh memiliki mesin hitung PO alternatif. Semua preview, edit, finalisasi, status, dan teks WhatsApp wajib memakai domain logic/API SPPG yang sama dengan aplikasi web.

## Source of truth yang sudah ada
- backend/purchase_order_workflow_api.py
- backend/inventory_projection_v2_api.py
- backend/po_reminder_v4_api.py
- backend/po_shortage_stock_api.py
- backend/po_schedule.py
- backend/stock_opname_parser.py

## Aturan yang wajib dipertahankan

1. **Draft dan revisi**
   - PO status DRAFT boleh diedit.
   - PO FINALIZED/SENT/ACKNOWLEDGED/PARTIAL_RECEIVED/RECEIVED tidak boleh ditimpa.
   - Perubahan setelah final harus melalui mekanisme revisi.
   - PO yang sudah memiliki receiving tidak boleh diedit langsung.

2. **Stok untuk rekomendasi PO**
   - Latest stock opname tetap physical anchor.
   - Tambahkan movement aktual setelah SO.
   - Kurangi actual usage.
   - Kurangi planning depletion yang belum tergantikan oleh actual usage.
   - Tambahkan committed PO supply yang belum menjadi goods receipt.
   - Gunakan available_for_po dari inventory projection yang sama dengan aplikasi.
   - Plugin tidak boleh mengubah stok fisik hanya karena PO dibuat.

3. **Coverage PO**
   - Coverage harus exact pada distribution date + ingredient type + canonical unit.
   - Jangan memakai fallback berdasarkan vendor/date/latest PO yang bisa menutup shortage secara salah.
   - Status coverage mengikuti stage yang sama: OPEN, DRAFT_NEEDS_FINAL, READY_TO_SEND, DONE.

4. **Vendor dan lead time**
   - Resolusi vendor serta procurement rule memakai rule engine existing.
   - Exception Tempe MAJA/CEMPLANG tetap mengikuti rule yang sudah ada.
   - Plugin tidak hard-code vendor/lead time baru.

5. **WhatsApp**
   - Gunakan format_purchase_order_whatsapp() sebagai formatter kanonik.
   - Teks yang tampil di plugin harus sama dengan Pusat Kontrol/GPTS.
   - Status SENT hanya dicatat setelah aksi kirim/tandai terkirim berhasil sesuai workflow.

6. **AI role**
   - AI boleh memahami perintah natural language dan membantu edit draft.
   - AI tidak boleh menjadi source of truth untuk qty rekomendasi, status, stok, vendor, lead time, coverage, atau mutasi database.
   - Semua write harus lewat endpoint/domain service resmi SPPG.

## Tahap rollout
- Fase 1: read-only preview dari engine existing.
- Fase 2: edit draft + diff terhadap rekomendasi.
- Fase 3: finalize/revision dengan confirmation.
- Fase 4: WhatsApp copy/open + SENT synchronization.
