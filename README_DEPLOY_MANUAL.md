# SPPG Finance Legacy UI Railway v7.9

Perbaikan:
- Tracking Harga & Hutang fit ke layar.
- Tidak perlu geser kanan-kiri untuk tabel utama tracking.
- Kolom item/note/ID dibuat wrap dan dipotong 2 baris agar rapi.
- Kolom angka dipadatkan dan tetap rata kanan.

Deploy:
```bash
BASE="/Users/zaetjd/Library/CloudStorage/GoogleDrive-jack7bear@gmail.com/My Drive/akuntan gpt"

cd "$BASE"

unzip -o "SPPG_Finance_Legacy_UI_Railway_v7_9.zip"

rsync -av --delete \
  --exclude=".git" \
  --exclude="node_modules" \
  --exclude="dist" \
  sppg-finance-legacy-ui-railway-v7_9/ \
  sppg-finance-railway-ready/

cd "$BASE/sppg-finance-railway-ready"

rm -rf node_modules dist
npm install
npm run build

git add -A
git commit -m "Fit tracking table without horizontal scroll v7.9"
git push
```
