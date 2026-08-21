# SPPG Hermes Lab v0.4

Eksperimen terisolasi untuk menghubungkan Custom GPT ke Hermes Agent. Hermes dapat membaca konteks, berbagi memory, dan membuat proposal staging yang wajib disetujui operator. Gateway Hermes tetap tidak memiliki endpoint approval atau eksekusi.

## Arsitektur

Custom GPT -> HTTPS `hermes_lab` gateway -> Hermes Agent API -> approved read-only tools / LLM Wiki

Kode gateway berada di repo yang sama dengan branch Railway `llm-wiki-v0`, tetapi image gateway tetap dibangun dan dijalankan terpisah di VM.

## Batas v0.4

- Data operasional tetap READ ONLY.
- Hermes boleh menulis shared memory dan proposal ke staging queue.
- Proposal selalu dimulai sebagai `PENDING`/`PLANNED`, membutuhkan approval OWNER, dan tidak pernah dieksekusi oleh gateway/Hermes.
- Tidak boleh membuat/mengubah/menghapus transaksi, PO, receiving, stok, file Drive, GitHub, Firestore, PostgreSQL, atau data SPPG lainnya.
- Tidak boleh mengirim WhatsApp/email/pesan.
- Hermes tidak menerima `SPPG_HERMES_APPROVAL_KEY`; kunci approval hanya milik operator/backend.
- Jangan memasukkan credential ke repository.

Sesudah approval terpisah, aplikasi Railway hanya boleh menjalankan capability `CREATE_PO_DRAFT`. Capability tersebut membuat PO berstatus `DRAFT` dan tetap tidak dapat memfinalkan PO, menandai terkirim, mengirim WhatsApp, atau menulis receiving/keuangan. Semua capability lain tetap terkunci.

Payload `CREATE_PO` wajib lengkap dan memakai snake_case:

```json
{
  "po_code": "PO-CEMPLANG-20260822-HOLIL",
  "distribution_date": "2026-08-22",
  "cooking_at": "2026-08-21T03:00:00+07:00",
  "status": "DRAFT",
  "items": [
    {"item_name": "Wortel", "po_qty": 10, "unit": "kg"}
  ]
}
```

Jangan mengisi nilai yang belum mempunyai sumber. Proposal tidak lengkap harus ditolak, bukan dilengkapi dengan tebakan.

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

Jalankan gateway Hermes (`hermes gateway`) di service yang terlindungi. Jangan mengekspos tool approval atau mutasi produksi pada gateway.

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
5. Jangan berikan endpoint approval, endpoint OWNER `create-po-draft`, atau kunci `SPPG_HERMES_APPROVAL_KEY` kepada Hermes.

### Instruksi GPT v0

- Gunakan Hermes Lab untuk analisis operasional SPPG yang membutuhkan penelusuran atau reasoning agentik.
- Semua tool gateway bersifat read-only atau staging-only.
- Untuk create/update/delete/send/commit/pay/approve, buat proposal bila schema lengkap; keputusan dan eksekusi DRAFT hanya dilakukan OWNER di aplikasi Railway.
- Jangan menebak site, tanggal, vendor, PO, atau identifier bila data tidak cukup.
- Bedakan data yang ditemukan, inferensi, dan ketidakpastian.

## Tes pertama

Sesudah Hermes dan gateway hidup:

1. `Cek status Hermes Lab.`
2. `Jelaskan aturan read-only kamu.`
3. `Cari apa yang kamu ketahui tentang vendor Holil tanpa mengubah data.`
4. Setelah LLM Wiki read-only tool terpasang: `Cek PO Cemplang untuk besok dan laporkan yang belum receiving.`

Tidak ada langkah di atas yang boleh menulis ke database produksi.
