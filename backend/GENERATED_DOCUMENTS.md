# Dokumen harian → LPDH

Pembuatan hanya di LPDH: `/lpdh?site=MAJA&tab=documents` atau `/lpdh?site=CEMPLANG&tab=documents`.
Alamat lama `/operations/documents` dialihkan ke LPDH. Modul Invoice & Pembayaran lama tetap tersedia untuk workflow pembayaran yang terpisah.

1. Pilih tanggal, jenis dokumen, kop, lalu beberapa item master/penerima. Tarif dan realisasi diperiksa akuntan; sumber harga contoh bukan transaksi baru.
2. Isi nomor invoice/paket PDF dan nomor tiap kuitansi secara manual. Simpan DRAFT lalu buka PDF di tab browser baru untuk pemeriksaan/cetak (tanpa unduh otomatis). Nomor dapat diedit selama DRAFT; nomor final dan riwayat dibatalkan tetap terkunci serta tidak dapat digunakan ulang.
3. **Finalkan** meminta konfirmasi. Snapshot final dan pengisian data harian dilakukan dalam satu transaksi. Jika impor gagal, dokumen tidak menjadi final.
4. Data harian menerima nomor, item, nilai, kategori, dan penerima dari dokumen final; penyimpanan ulang memulihkan snapshot tersebut. Link bukti pembayaran/hasil tanda tangan boleh dilengkapi.
5. Operasional mendukung beberapa invoice per tanggal. Sheet C menjumlahkan item per kategori dan menyertakan semua nomor invoice. Register mencatat satu bukti per invoice, bukan per item.
6. Upah relawan dan insentif guru/kader selalu satu hari per penerima. Satu PDF upah dan satu PDF insentif berisi kuitansi individual bernomor unik. Pembayaran penerima yang sama dua kali pada tanggal yang sama ditolak.
7. Kalender menampilkan semua jenis dokumen per tanggal dan dapur, termasuk hitungan draft/final/dibatalkan. Klik tanggal untuk membuka register.
8. Finalisasi otomatis mencoba mengarsipkan PDF final menggunakan penyimpanan invoice SPPG Drive yang sama dengan Akuntan, terpisah per dapur. Status upload dan tautan terlihat di register; kegagalan upload tidak membatalkan transaksi final/data harian dan dapat dicoba ulang. Klik ulang tidak mengunggah ulang jika URI sudah tercatat. Upload Drive dan PostgreSQL bukan transaksi terdistribusi: kegagalan proses tepat setelah upload sebelum penyimpanan URI dapat meninggalkan salinan arsip.
9. Batalkan dengan alasan dan konfirmasi: status menjadi CANCELLED dan biaya bersumber dokumen dibangun ulang secara atomik, termasuk bila invoice terakhir dibatalkan. Riwayat, nomor, dan arsip Drive lama tetap disimpan sebagai bukti historis; jangan memakai PDF arsip lama sebagai dokumen aktif. PDF yang dibuka ulang dari aplikasi ditandai DIBATALKAN. Pengganti dibuat dengan nomor baru. Dokumen dibatalkan tidak bisa difinalkan kembali. Bila LPDH sudah GENERATED, pembatalan ditolak sampai data harian disimpan sebagai draft. Tidak ada penghapusan pembayaran/maker pusat operasional.

10. Sebelum finalisasi, status dibaca ulang dari server. Tab lama tidak dapat memfinalkan dokumen yang sudah dibatalkan. Tombol Buat ulang menyalin item menjadi isian draft baru dengan nomor dan referensi pembayaran kosong, tanpa mengaktifkan riwayat lama.
11. Kop/logo, stempel dan TTD diunggah manual sebagai PNG/JPEG/WebP, maksimal 5 MB dan 16 megapiksel. File asli disimpan privat dan immutable dengan akses sesuai dapur/peran. PDF memakai ID gambar snapshot dokumen; mengganti default tidak mengubah PDF historis. TTD penerima invoice tidak dipakai ulang sebagai TTD individu pada kuitansi.
12. Simpan data kop sebagai default atau Simpan draft menyimpan identitas, rekening, penandatangan, metode pembayaran dan referensi gambar per dapur/profil. Default berlaku sampai diisi ulang. Nomor, tanggal, item, nominal, referensi dan bukti pembayaran bukan default transaksi.

Kop, alamat, rekening, logo dan nama penandatangan Maja berasal dari empat PDF contoh yang diberikan pengguna. Identitas, rekening dan harga referensi dimuat dari konfigurasi privat Railway `LPDH_MAJA_DOCUMENT_REFERENCE` (objek `profiles` dan `operationItems`), bukan hardcode publik. Gambar tanda tangan/stempel pribadi tidak disertakan di repositori publik; unggahan operator disimpan privat di database aplikasi. Tarif historis mingguan/bulanan tidak dijadikan tarif harian; sewa mobil dan nominal yang belum diketahui harus diisi. Data kop Cemplang harus dilengkapi oleh operator, bukan menyalin Maja.

Dokumen final tidak mengubah tabel maker/pembayaran pusat operasional lama. Integrasi maker otomatis di luar LPDH belum diaktifkan, sesuai permintaan pengguna.

## Validasi lokal (tanpa data produksi)

- `python backend/lpdh_selftest.py`
- `python backend/generated_document_selftest.py`
- `python tests/test_generated_document_api.py` (FastAPI/Pydantic sesuai requirements, httpx untuk TestClient; jalankan proses terpisah)
- `node --test tests/generated-documents-ui.test.cjs tests/operations-navigation.test.mjs tests/operations-auto-read.test.cjs` (react-test-renderer 18.3.1 sebagai alat uji lokal)
- `npm run build`

Migrasi v038/v039/v040/v041 mempertahankan data lama. Tidak menghapus atau mengonversi riwayat pembayaran lama. Finalisasi, pembatalan, simpan data harian, dan generate workbook memakai kunci transaksi tanggal/site yang sama agar biaya yang sudah difinalkan tidak tertimpa proses lain. v041 menambah penyimpanan gambar privat, default kop terpisah dari master keuangan, dan reservasi nomor unik termasuk riwayat dibatalkan.
