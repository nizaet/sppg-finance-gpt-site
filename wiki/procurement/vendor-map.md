# Vendor Map

Current mapping:
- Sayur & buah -> Holil.
- **Tempe Maja -> Koperasi via Mungki; rule lead time terpisah dari Tahu.**
- Tahu Maja -> Koperasi via Mungki; dibayar kas; reimburse internal akhir bulan.
- **Tempe Cemplang -> Koperasi; dedicated lead time belum ditetapkan.**
- Ayam -> Wikian.
- Telur -> via Mungki; dibayar kas; reimburse internal akhir bulan.
- Ikan -> Rumah Duta Pangan.
- Gas -> Heru.
- Beras -> Dede.
- Tahu Cemplang -> Haji Badri.
- Bahan kering -> stok Koperasi via Mungki.
- Upstream stok bahan kering Koperasi -> Indogrosir.

Vendor baru tidak boleh di-hard-code secara generik. Mapping operasional harus berasal dari master/vendor rule yang terkonfirmasi, dan histori PO lama tidak boleh berubah jika vendor default diganti.

Untuk reminder PO, keberadaan PO dari vendor yang sama **tidak** berarti kebutuhan sudah tercakup. Coverage harus cocok pada tanggal distribusi dan item/unit/qty yang dibutuhkan.
