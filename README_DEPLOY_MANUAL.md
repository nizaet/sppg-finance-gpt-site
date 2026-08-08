# SPPG Finance Legacy UI Railway v7.1

Versi ini dibuat supaya Git pasti melihat perubahan saat Anda copy ke repo.

Ciri v7.1:
- `package.json` version = `7.1.0`
- Ada file `VERSION.txt`
- Tab AI dihapus dari navigasi.
- Tulisan tab kecil "Bulk Upload Lokal" di halaman Input dihapus.
- Audit bisa edit kategori/vendor/paid langsung.
- Hutang bisa dilunasi sesuai filter vendor/kategori.
- Kategori lokal belajar dari transaksi manual/backup yang sudah diedit.
- Laporan lebih compact supaya tidak terlalu geser kanan-kiri.

Deploy:
```bash
rsync -av --delete --exclude=".git" sppg-finance-legacy-ui-railway-v7_1/ sppg-finance-railway-ready/
cd sppg-finance-railway-ready
npm install
npm run build
git status -sb
git add .
git commit -m "Improve legacy finance app v7.1"
git push
```
