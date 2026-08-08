# SPPG Finance Legacy UI Railway v7.2

Perbaikan utama:
- Restore JSON tidak lagi mengubah kategori backup.
- Kategori dari backup/manual/GPT dianggap data benar.
- Sistem belajar kategori dari histori, tetapi hanya dipakai untuk transaksi baru/kosong.
- Dropdown kategori otomatis memuat kategori lama dari backup.
- Tab dibuat sejajar horizontal ke kanan.
- Grafik dashboard diperbaiki: data disanitasi dan bar tidak distack.
- Laporan dibuat lebih compact agar fit.

Deploy:
```bash
cd "/Users/zaetjd/Library/CloudStorage/GoogleDrive-jack7bear@gmail.com/My Drive/akuntan gpt"
unzip -o "SPPG_Finance_Legacy_UI_Railway_v7_2.zip"
rsync -av --delete --exclude=".git" sppg-finance-legacy-ui-railway-v7_2/ sppg-finance-railway-ready/
cd sppg-finance-railway-ready
rm -rf node_modules dist
npm install
npm run build
git status -sb
git add .
git commit -m "Fix restore categories layout and dashboard charts v7.2"
git push
```
