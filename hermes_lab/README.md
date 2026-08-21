# SPPG Hermes Lab v0.3

Eksperimen terisolasi untuk menghubungkan Custom GPT ke Hermes Agent. Hermes dapat membaca konteks, berbagi memory, dan membuat proposal staging yang wajib disetujui operator; tidak ada eksekusi produksi.

## Arsitektur

Custom GPT -> HTTPS `hermes_lab` gateway -> Hermes Agent API -> approved read-only tools / LLM Wiki

Branch ini sengaja terpisah dari `main` dan `llm-wiki-v0`.

## Batas v0.3

- Data operasional tetap READ ONLY.
- Hermes boleh menulis shared memory dan proposal ke staging queue.
- Proposal selalu `PENDING`/`PLANNED`, membutuhkan approval, dan tidak pernah mengeksekusi aksi.
- Tidak boleh membuat/mengubah/menghapus transaksi, PO, receiving, stok, file Drive, GitHub, Firestore, PostgreSQL, atau data SPPG lainnya.
- Tidak boleh mengirim WhatsApp/email/pesan.
- Hermes tidak menerima `SPPG_HERMES_APPROVAL_KEY`; kunci approval hanya milik operator/backend.
- Jangan memasukkan credential ke repository.

## Environment gateway

- `HERMES_API_URL` = URL Hermes Agent, tanpa `/v1` di akhir.
- `HERMES_API_KEY` = `API_SERVER_KEY` milik Hermes.
- `LAB_GATEWAY_KEY` = secret khusus yang dipasang juga sebagai API key di Custom GPT Action.
- `HERMES_MODEL` = opsional, default `hermes-agent`.
- `SPPG_CORE_URL` = URL Railway SPPG Core.
- `SPPG_GPT_API_KEY` = kunci gateway untuk context, memory, dan pembuatan proposal saja.

## Hermes Agent

Hermes menyediakan OpenAI-compatible API server. Konfigurasi dasar di runtime Hermes:

```env
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=<secret-kuat>
```

Jalankan gateway Hermes (`hermes gateway`) di service yang terlindungi. Jangan mengekspos tool mutasi produksi pada fase v0.

## Deploy gateway

Dockerfile: `hermes_lab/Dockerfile`

Contoh start command bila tidak menggunakan Dockerfile:

```bash
uvicorn hermes_lab.app:app --host 0.0.0.0 --port $PORT
```

Setelah deploy, cek:

`GET /health`

Harus menampilkan `mode: read_operational_write_memory_propose_actions`, `hermes_configured: true`, dan `action_execution_exposed: false`.

## Custom GPT

1. Buat GPT baru: `SPPG Hermes Lab`.
2. Tambahkan Action dari `hermes_lab/openapi.yaml`.
3. Ganti server placeholder dengan URL HTTPS gateway.
4. Auth Action: Bearer/API Key = nilai `LAB_GATEWAY_KEY`.
5. Jangan berikan endpoint approval atau kunci `SPPG_HERMES_APPROVAL_KEY` kepada Hermes.

### Instruksi GPT v0

- Gunakan Hermes Lab untuk analisis operasional SPPG yang membutuhkan penelusuran atau reasoning agentik.
- Semua operasi bersifat read-only.
- Untuk create/update/delete/send/commit/pay/approve, tampilkan proposal dan minta user menggunakan sistem produksi yang sesuai.
- Jangan menebak site, tanggal, vendor, PO, atau identifier bila data tidak cukup.
- Bedakan data yang ditemukan, inferensi, dan ketidakpastian.

## Tes pertama

Sesudah Hermes dan gateway hidup:

1. `Cek status Hermes Lab.`
2. `Jelaskan aturan read-only kamu.`
3. `Cari apa yang kamu ketahui tentang vendor Holil tanpa mengubah data.`
4. Setelah LLM Wiki read-only tool terpasang: `Cek PO Cemplang untuk besok dan laporkan yang belum receiving.`

Tidak ada langkah di atas yang boleh menulis ke database produksi.
