# Deploy Manual — SPPG Finance Legacy UI Railway

Paket ini mengembalikan bentuk aplikasi lama:
- Laporan Keuangan SPPG MAJA BARU
- Tab Dash, Input, Hutang, Laporan, Dividen, Gudang, AI
- Tambahan tab Audit tanpa membuang tab lama
- CSS biasa, tidak memakai Tailwind

Mesin data baru:
- Membaca Firebase Firestore path:
  `gpt_sites/sppg-maja-gpt-site/ledger/meta/transactions`
- Kompatibel dengan data dari Custom GPT Action.
- Hutang memakai `paymentStatus`, `paidAmount`, dan outstanding = amount - paidAmount.

## Cara pakai

Copy isi folder ini ke folder repo lokal:

```bash
cd "/Users/zaetjd/Library/CloudStorage/GoogleDrive-jack7bear@gmail.com/My Drive/akuntan gpt/sppg-finance-railway-ready"
cp -R /path/hasil-unzip/* .
npm install
npm run build
git add .
git commit -m "Restore legacy UI with Firebase GPT engine"
git push
```

Railway akan redeploy otomatis.
