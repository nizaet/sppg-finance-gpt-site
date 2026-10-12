# Membatalkan dokumen dan memilih file BGN

Pembatalan pengesahan, invoice/kuitansi akuntan, kuitansi TopUp dan penghapusan
baris TopUp dengan kuitansi FINAL menawarkan SIMPAN (default) atau SAMPAH.
Menutup dialog/mengetik pilihan lain tidak menjalankan pembatalan.
Hanya file BGN aktif yang teridentifikasi di catatan upload dokumen tersebut
yang boleh dipindahkan; salinan internal, riwayat dan folder tidak dihapus.
Tidak ada operasi hapus permanen. Pemulihan dilakukan melalui Sampah Drive
dengan akun yang memiliki izin; tindakan ini tidak membatalkan transfer bank.

Guard Maker/antrean invoice tetap berjalan sebelum membuat permintaan Sampah.
Permintaan disimpan bersama transaksi pembatalan, sedangkan operasi Google
berjalan setelah commit agar kegagalan validasi tidak menghapus file.
Situs, akun akuntan, marker artifact, parent tanggal/bulan/root dapur serta
izin canTrash diperiksa sebelum update trashed=true dan readback Google.

Jika Google gagal atau hasil belum terkonfirmasi, pembatalan tetap tersimpan.
Permintaan PENDING/FAILED tampil pada Koneksi Drive BGN dapur terkait dengan
tombol coba lagi. Retry terikat situs dan id permintaan server, bukan URL
arbitrer dari browser. File yang sudah berada di Sampah tidak dipindah ulang.
File legacy/tidak tercatat di transport BGN tidak dihapus dan menghasilkan
pesan SKIPPED. Tidak ada pemindahan massal file lama.
