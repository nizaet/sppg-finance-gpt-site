# SPPG Finance Legacy UI Railway v7.6

Perbaikan:
- Tracking Harga & Hutang tidak lagi sulit dicari; bisa sort berdasarkan terakhir input.
- Semua transaksi sesuai filter tampil, bukan dibatasi 250 pertama tanpa sort.
- Filter status: Semua, Hutang aktif, Lunas, Pemasukan, Pengeluaran, Ada qty/harga.
- Filter kategori dan search vendor/invoice/item.
- Tab Hutang lebih konsisten membaca `isDebt`, `paymentStatus=unpaid`, dan outstanding.

Deploy:
```bash
BASE="/Users/zaetjd/Library/CloudStorage/GoogleDrive-jack7bear@gmail.com/My Drive/akuntan gpt"

cd "$BASE"

unzip -o "SPPG_Finance_Legacy_UI_Railway_v7_6.zip"

rsync -av --delete \
  --exclude=".git" \
  --exclude="node_modules" \
  --exclude="dist" \
  sppg-finance-legacy-ui-railway-v7_6/ \
  sppg-finance-railway-ready/

cd "$BASE/sppg-finance-railway-ready"
rm -rf node_modules dist
npm install
npm run build
git add -A
git commit -m "Improve tracking harga hutang sorting and filters v7.6"
git push
```
