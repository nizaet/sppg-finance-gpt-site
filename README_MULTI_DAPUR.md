# SPPG Finance v8.0 — Multi-Dapur dengan Database Terpisah

## Prinsip
Maja tidak dipindah dan tidak disentuh:
- database: `(default)`
- siteId: `sppg-maja-gpt-site`

Cemplang 2:
- database: `cemplang2`
- siteId: `sppg-cemplang2-gpt-site`

Kedua aplikasi memakai codebase/repo yang sama. Buat dua Railway services dari repo dan branch yang sama.
Setiap commit baru ke repo akan membuat keduanya menerima source code yang sama secara otomatis.

## Environment Railway Maja
VITE_SITE_ID=sppg-maja-gpt-site
VITE_FIRESTORE_DATABASE_ID=(default)
VITE_SITE_LABEL=SPPG MAJA BARU
VITE_SITE_SHORT_LABEL=Maja

## Environment Railway Cemplang 2
VITE_SITE_ID=sppg-cemplang2-gpt-site
VITE_FIRESTORE_DATABASE_ID=cemplang2
VITE_SITE_LABEL=SPPG CEMPLANG 2
VITE_SITE_SHORT_LABEL=Cemplang 2

## Catatan
Firebase web SDK menggunakan named database untuk Cemplang 2.
Jangan membuat selector database di UI: setiap Railway service dikunci ke satu database agar tidak salah input.
