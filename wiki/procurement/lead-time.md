# Procurement Lead Time

Anchor: **waktu masak**, bukan tanggal distribusi.

Current confirmed rules:
- Sayur & buah: mengikuti rule vendor/site aktif.
- Ayam: H-3 sebelum masak.
- **Tempe Maja: H-4 sebelum masak, vendor Koperasi. Tempe adalah rule tersendiri dan tidak boleh memakai lead time Tahu.**
- **Tahu Maja: H-2 sebelum masak**, dipertahankan dari rule operasional lama setelah rule gabungan Tempe/Tahu dipecah.
- **Tempe Cemplang: vendor Koperasi; lead time khusus belum ditetapkan. Jangan mengambil lead time Tahu atau bahan kering sebagai fallback.**

Example:
Jika Tempe Maja dimasak Rabu, H-4 berarti tanggal pesan jatuh pada Sabtu. Jika PO belum selesai setelah tanggal tersebut, pengingat tetap tampil sebagai TERLAMBAT sampai kebutuhan benar-benar tercakup.

Reminder coverage rule:
PO hanya dianggap menyelesaikan kebutuhan jika coverage cocok pada **site + vendor + tanggal distribusi + jenis item + unit + qty**. Kesamaan vendor atau tanggal kirim PO saja tidak cukup.

Lead time harus configurable per vendor/item/site dan dapat berbeda jika pola operasional berubah.
