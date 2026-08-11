# SPPG Core Backend — Deploy Contract

## Target architecture

- Existing React/Vite site stays as frontend.
- `backend/` runs as a separate Railway service.
- Railway PostgreSQL provides `DATABASE_URL`.
- Frontend receives `VITE_SPPG_CORE_API_URL`.
- Google Drive remains immutable evidence storage.
- GitHub LLM Wiki remains knowledge/rules/provenance layer.

## Railway backend service

Build from repository `nizaet/sppg-finance-gpt-site` using branch selected for deployment.
Use Dockerfile path:

`backend/Dockerfile`

Required backend variables:

- `DATABASE_URL` — reference Railway PostgreSQL variable.
- `SPPG_ALLOWED_ORIGINS` — comma-separated frontend origins.

Health endpoint:

`GET /health`

Expected after DB is connected:

```json
{"status":"ok","service":"sppg-core","databaseReady":true}
```

## Database initialization

Run once after PostgreSQL is attached:

```bash
python -m backend.migrate
```

Migration runner applies:

1. `schema/reference_master_v09.sql`
2. `schema/reference_seed_v09.sql`
3. `schema/staging_v05.sql`
4. `schema/core_domain_v05.sql`

All current migrations use `create table if not exists` / conflict-safe seed patterns so they are designed to be repeatable during this bootstrap phase.

## Frontend

Set:

`VITE_SPPG_CORE_API_URL=https://<backend-service-domain>`

Do not put `DATABASE_URL` in Vite/frontend variables.

## Safety gates

- Candidate WhatsApp/chat events enter staging first.
- Payment/approval/BGN/settlement events require review.
- No parser event writes a financial ledger directly.
- Existing calculator planning data remains independent from `po_qty`, received quantities, actual usage, and payments.

## Go-live order

1. PostgreSQL provisioned.
2. Backend service deployed.
3. Migration applied.
4. `/health` returns `databaseReady=true`.
5. Test candidate event ingest.
6. Test review queue.
7. Configure frontend API URL.
8. Enable Pusat Operasional navigation.
9. Keep calculator modules unchanged during initial validation.
