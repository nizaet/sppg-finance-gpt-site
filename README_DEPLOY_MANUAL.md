# SPPG Finance Legacy UI Railway v7.4

Perbaikan:
- Firebase web config diberi fallback langsung di aplikasi.
- Railway tetap bisa terhubung ke Firebase meskipun env `VITE_FIREBASE_*` kosong.
- Cloud Backup sekarang full snapshot: transactions, inventory, shareholders.
- Cloud Restore bisa mengembalikan isi backup cloud, bukan metadata saja.
- Gudang membaca path yang sama dengan Worker:
  `gpt_sites/sppg-maja-gpt-site/ledger/meta/inventory`.

Deploy:
```bash
BASE="/Users/zaetjd/Library/CloudStorage/GoogleDrive-jack7bear@gmail.com/My Drive/akuntan gpt"

cd "$BASE"

unzip -o "SPPG_Finance_Legacy_UI_Railway_v7_4.zip"

rsync -av --delete \
  --exclude=".git" \
  --exclude="node_modules" \
  --exclude="dist" \
  sppg-finance-legacy-ui-railway-v7_4/ \
  sppg-finance-railway-ready/

cd "$BASE/sppg-finance-railway-ready"

rm -rf node_modules dist
npm install
npm run build

git add -A
git commit -m "Fix Firebase connection and full cloud backup restore v7.4"
git push
```
