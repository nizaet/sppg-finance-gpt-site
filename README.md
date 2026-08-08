# SPPG Finance GPT Site — Railway Ready

Dashboard React/Vite untuk membaca data transaksi SPPG dari Firebase Firestore.

## Backend yang sudah aktif

Custom GPT Action -> Cloudflare Worker -> Firebase Firestore

Worker URL:
https://ingest.sppg-gpt-ingest.workers.dev

Firestore path:
gpt_sites/sppg-maja-gpt-site/ledger/meta/transactions

## Deploy ke Railway dari GitHub

1. Buat repo GitHub baru:
   `sppg-finance-gpt-site`

2. Upload semua file folder ini ke repo.

3. Di Railway:
   - New Project
   - Deploy from GitHub repo
   - Pilih repo `sppg-finance-gpt-site`

4. Set Variables di Railway:

```
VITE_FIREBASE_API_KEY=AIzaSyB72MVySugfHF_vu11WYv-s9uiQbRpftk4
VITE_FIREBASE_AUTH_DOMAIN=sppg-finance-gpt.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=sppg-finance-gpt
VITE_FIREBASE_STORAGE_BUCKET=sppg-finance-gpt.firebasestorage.app
VITE_FIREBASE_MESSAGING_SENDER_ID=732611890148
VITE_FIREBASE_APP_ID=1:732611890148:web:5dcfab93d1d351b10315f1
VITE_FIREBASE_MEASUREMENT_ID=G-DZERB61197
VITE_SITE_ID=sppg-maja-gpt-site
```

5. Deploy.

## Build Commands

Railway akan membaca `railway.json`.

Build:
`npm install && npm run build`

Start:
`npm run start`

## Catatan

Untuk tahap tes, Firestore Rules bisa dibuat longgar:

```js
rules_version = '2';

service cloud.firestore {
  match /databases/{database}/documents {
    match /gpt_sites/{siteId}/{document=**} {
      allow read, write: if true;
    }
  }
}
```

Setelah dashboard stabil, rules sebaiknya dikunci.
