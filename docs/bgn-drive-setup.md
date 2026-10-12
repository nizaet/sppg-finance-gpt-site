# Koneksi Drive BGN dan bukti LPDH

Status implementasi: OAuth per dapur, pemilihan folder, tes upload, dan
integrasi finalisasi invoice/TopUp/pengesahan ke BGN tersedia. Arsip internal
untuk Maker tetap terpisah; bukti lama tidak dipindah otomatis.

Tombol Tes Upload BGN membuat PDF deterministik bertanda BUKAN BUKTI
TRANSAKSI untuk tanggal HPE aktif. Endpoint memeriksa dapur dan HPE serta
ukuran, MD5, mimeType, parent folder dan status trashed hasil readback Google.
Tes hanya menulis catatan pada lpdh_bgn_drive_uploads; tidak membuat invoice,
Maker atau mengubah saldo/data harian. Tes berulang menggunakan artifact key
dan content hash yang sama. File uji tidak dihapus otomatis.

## Konfigurasi server

- `SPPG_BGN_DRIVE_PICKER_API_KEY`: key baru khusus Google Picker API,
  website restrictions `https://sppg-finance-gpt-site-production-5b7d.up.railway.app/*`
  dan `https://docs.google.com/*` (iframe Picker). Jangan menonaktifkan restrictions.
- `SPPG_BGN_DRIVE_TOKEN_KEY`: Fernet key (32 byte acak, URL-safe base64).
  Buat dan pasang melalui pengelola secret Railway, jangan commit/cetak ke log.
  Simpan backup aman; mengganti key membuat akun perlu dihubungkan ulang.
- OAuth Client ID dan Client Secret menggunakan konfigurasi client Drive
  backend yang sudah ada. Refresh token Drive internal **tidak** dipakai BGN.
- Callback Google Cloud:
  `https://sppg-finance-gpt-site-production-5b7d.up.railway.app/v1/lpdh/bgn-drive/oauth/callback`.
- Scopes: `openid`, email, `https://www.googleapis.com/auth/drive.file`.
- Google Picker API aktif. Akuntan memberi akses folder lewat Picker;
  menyimpan ID folder saja tidak memberikan izin Google.

## Tujuan tetap per dapur

- MAJA: `nakamotoy306@gmail.com`, folder `15-XbfpHjrf_PVTnSw12o7XUBrQcGeNaU`.
- CEMPLANG: `lidiyamaulidiya2020@gmail.com`, folder `15qKQFAP4UqPU-o3hmc50SW5tDRkZC9qF`.
- Di bawah root BGN: `YYYY-MM/YYYY-MM-DD`, memakai tanggal pelayanan HPE.
- Pengguna tidak dapat mengganti tujuan menjadi folder dapur lain.

## Pengamanan

OAuth state memiliki expiry 10 menit, sekali pakai, terikat cookie browser dan
PKCE S256. Callback menyembunyikan query code dari access log. Email Google
harus verified dan cocok dengan dapur; refresh token disimpan dengan Fernet.
Token akses Picker hanya dikirim sesaat ke browser yang sudah login, no-store,
tidak disimpan di localStorage. Putuskan koneksi menghapus token lokal saja,
tidak menghapus berkas Drive atau koneksi internal.

Koneksi disimpan per dapur, bukan per PC. Login ulang dengan email akuntan
yang sama mempertahankan folder terpilih. Tombol Periksa Koneksi melakukan
pemeriksaan langsung token Google dan izin tulis folder, tanpa membuat berkas,
serta menampilkan hasil dan waktu pemeriksaan. Status tersimpan saja bukan
bukti bahwa token Google masih aktif.

## Integrasi finalisasi (v052)

Finalisasi invoice akuntan (termasuk kuitansi relawan/guru/kader dan insentif
mitra), kuitansi TopUp, J_Pengesahan, serta upload bukti TopUp menggunakan
dua tujuan: PDF BGN untuk link LPDH, arsip internal untuk Maker.
BGN memverifikasi parent, ukuran dan checksum file setelah upload. Folder
BGN mengikuti tanggal pelayanan `YYYY-MM/YYYY-MM-DD`, bukan waktu upload.
Tidak mengubah nominal, status pembayaran bank, atau bukti lama secara massal.

Invoice mempertahankan status FINAL saat upload gagal (alur lama); status/error
BGN terpisah dan tombol Simpan ke Drive dapat mencoba lagi tanpa mengunggah
ulang PDF/Excel internal yang sudah tersimpan. Link internal tidak menjadi
fallback LPDH untuk invoice yang dikelola BGN. Snapshot LPDH GENERATED tidak
ditulis ulang oleh retry arsip. Kuitansi TopUp dan pengesahan baru menjadi
FINAL setelah kedua arsip lengkap; kegagalan menyisakan draft/data lama.
Final lama tidak otomatis dipindah. Pastikan kedua dapur tersambung sendiri.

## Riwayat tahap koneksi

1. Deploy migrasi dan halaman Koneksi Drive BGN tanpa mengganti alur bukti.
2. Pasang dua konfigurasi server tanpa menampilkan nilainya di chat/log.
3. Akuntan login sendiri dan memilih root BGN melalui Picker.
4. Verifikasi akses tulis kedua dapur; uji upload hanya dengan bukti uji yang
   disetujui pengguna, tidak memfinalkan transaksi asli untuk pengujian.
5. Implementasikan integrasi dual-upload, status per tujuan, retry dan link
   BGN untuk LPDH; Maker tetap memakai link internal. Jangan menandai tahap
   integrasi selesai hanya karena akun telah terhubung.

Pengujian lokal: `tests/test_bgn_drive.py` (8 security contracts) dan build UI.

