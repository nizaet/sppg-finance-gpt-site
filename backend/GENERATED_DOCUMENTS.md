# Dokumen harian → LPDH

Tab produksi: `/operations/documents?site=MAJA` atau `/operations/documents?site=CEMPLANG`.
Tab yang sama tersedia dalam LPDH sebagai **Buat Invoice & Kuitansi**.

1. Pilih tanggal, jenis dokumen, kop, lalu beberapa item master/penerima. Tarif dan realisasi diperiksa akuntan; sumber harga contoh bukan transaksi baru.
2. Simpan DRAFT: nomor dibuat oleh server. Unduh PDF asli untuk pemeriksaan/cetak, atau edit isi draft dengan nomor yang sama.
3. **Finalkan** meminta konfirmasi. Snapshot final dan pengisian data harian dilakukan dalam satu transaksi. Jika impor gagal, dokumen tidak menjadi final.
4. Data harian menerima nomor, item, nilai, kategori, dan penerima dari dokumen final; penyimpanan ulang memulihkan snapshot tersebut. Link bukti pembayaran/hasil tanda tangan boleh dilengkapi.
5. Operasional mendukung beberapa invoice per tanggal. Sheet C menjumlahkan item per kategori dan menyertakan semua nomor invoice. Register mencatat satu bukti per invoice, bukan per item.
6. Upah relawan dan insentif guru/kader selalu satu hari per penerima. Satu PDF upah dan satu PDF insentif berisi kuitansi individual bernomor unik. Pembayaran penerima yang sama dua kali pada tanggal yang sama ditolak.

Kop, alamat, rekening, logo dan nama penandatangan Maja berasal dari empat PDF contoh yang diberikan pengguna. Identitas, rekening dan harga referensi dimuat dari konfigurasi privat Railway `LPDH_MAJA_DOCUMENT_REFERENCE` (objek `profiles` dan `operationItems`), bukan hardcode publik. Gambar tanda tangan/stempel pribadi tidak disertakan di repositori publik; PDF menyediakan ruang tanda tangan, kemudian hasil bertanda tangan dapat ditautkan sebagai bukti. Tarif historis mingguan/bulanan tidak dijadikan tarif harian; sewa mobil dan nominal yang belum diketahui harus diisi. Data kop Cemplang harus dilengkapi dari master/operator, bukan menyalin Maja.

Dokumen final tidak mengubah tabel maker/pembayaran pusat operasional lama. Integrasi maker otomatis di luar LPDH belum diaktifkan, sesuai permintaan pengguna.

## Validasi lokal (tanpa data produksi)

- `python backend/lpdh_selftest.py`
- `python backend/generated_document_selftest.py`
- `python tests/test_generated_document_api.py` (FastAPI/Pydantic sesuai requirements, httpx untuk TestClient; jalankan proses terpisah)
- `node --test tests/generated-documents-ui.test.cjs tests/operations-navigation.test.mjs tests/operations-auto-read.test.cjs` (react-test-renderer 18.3.1 sebagai alat uji lokal)
- `npm run build`

Migrasi v038/v039 additive. Tidak menghapus atau mengonversi riwayat pembayaran lama. Finalisasi, simpan data harian, dan generate workbook memakai kunci transaksi tanggal/site yang sama agar biaya yang sudah difinalkan tidak tertimpa proses lain.
