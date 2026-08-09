# SPPG Finance Legacy UI Railway v7.8

Perbaikan:
- Hutang yang statusnya unpaid tetapi paidAmount lama = amount tidak lagi tampil Rp0.
- Checkbox Hutang di modal Edit sekarang mengikuti paymentStatus/isDebt/outstanding.
- Jika dipilih Hutang, paidAmount otomatis 0.
- Jika Lunas, paidAmount otomatis sebesar total.
- Confirm hapus dari popup rincian tampil di depan, tidak ketutup popup rincian.
- Tracking Harga & Hutang dibuat full lebar dengan filter lengkap:
  periode, bulan, custom tanggal, kategori, vendor, status, sort recent.
- Tabel tracking menampilkan qty, satuan, harga/unit, total, outstanding, dan tombol edit/delete.
- Form input manual serta paste pemasukan/pengeluaran dipindah ke bawah.

Deploy:
```bash
BASE="/Users/zaetjd/Library/CloudStorage/GoogleDrive-jack7bear@gmail.com/My Drive/akuntan gpt"

cd "$BASE"

unzip -o "SPPG_Finance_Legacy_UI_Railway_v7_8.zip"

rsync -av --delete \
  --exclude=".git" \
  --exclude="node_modules" \
  --exclude="dist" \
  sppg-finance-legacy-ui-railway-v7_8/ \
  sppg-finance-railway-ready/

cd "$BASE/sppg-finance-railway-ready"

rm -rf node_modules dist
npm install
npm run build

git add -A
git commit -m "Fix debt edit modal and full width tracking v7.8"
git push
```
