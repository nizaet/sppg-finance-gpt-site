# SPPG Core Backend — Deploy Contract

## Target architecture

- Existing React/Vite site stays as frontend.
- `backend/` runs as a separate Railway service.
- Railway PostgreSQL provides `DATABASE_URL`.
- Frontend receives `VITE_SPPG_CORE_API_URL`.
- Firestore remains the existing finance UI ledger used by the Maja/Cemplang app.
- PostgreSQL keeps the operational domain plus the ChatGPT finance bridge audit mirror.
- Google Drive stores immutable raw evidence / exchange files.
- GitHub LLM Wiki stores rules, mappings, provenance, and durable operational knowledge.

## Railway backend service

Build from repository `nizaet/sppg-finance-gpt-site` branch `llm-wiki-v0`.
Railway root configuration uses:

`railway.json`

which points to:

`backend/Dockerfile`

Health endpoint:

`GET /health`

The container starts in degraded mode when `DATABASE_URL` is absent, so health/OpenAPI can still load. Transactional endpoints remain unavailable until PostgreSQL is attached.

Expected with DB connected:

```json
{"status":"ok","service":"sppg-core","version":"0.11.0","databaseReady":true}
```

## Required backend variables

### PostgreSQL

- `DATABASE_URL` — Railway PostgreSQL connection URL.

The container runs `python -m backend.migrate` automatically whenever `DATABASE_URL` exists.

### CORS

- `SPPG_ALLOWED_ORIGINS` — comma-separated allowed frontend origins.

### ChatGPT bridge authentication

- `SPPG_GPT_API_KEY` — strong random secret used as `Authorization: Bearer <secret>` by the ChatGPT Action.

If the variable is absent, every `/v1/gpt/*` route returns 503 rather than becoming public.

### Google Firestore + Drive

Create one Google service account in the Firebase/Google Cloud project that owns Firestore (`sppg-finance-gpt`) and provide:

- `SPPG_GOOGLE_SERVICE_ACCOUNT_JSON` — complete service-account JSON as one Railway environment variable.
- `SPPG_FIRESTORE_PROJECT_ID=sppg-finance-gpt`

That identity must have permission to write Firestore and must be shared into the Drive archive root folder. The same credential is intentionally reused for both services.

Drive folder variables:

- `SPPG_DRIVE_ROOT_FOLDER_ID`
- `SPPG_DRIVE_RAW_CHAT_FOLDER_ID`
- `SPPG_DRIVE_PO_VENDOR_FOLDER_ID`
- `SPPG_DRIVE_ACCOUNTANT_FOLDER_ID`
- `SPPG_DRIVE_BGN_APPROVER_FOLDER_ID`
- `SPPG_DRIVE_KOPERASI_STOCK_FOLDER_ID`
- `SPPG_DRIVE_REVIEW_EXPORT_FOLDER_ID`
- `SPPG_DRIVE_BACKUP_FOLDER_ID`

Real folder IDs must stay in Railway environment configuration, not in this public repository.

## Database initialization

`backend.migrate` applies:

1. `schema/reference_master_v09.sql`
2. `schema/reference_seed_v09.sql`
3. `schema/staging_v05.sql`
4. `schema/core_domain_v05.sql`
5. `schema/planning_bridge_v010.sql`
6. `schema/finance_ledger_v011.sql`

Migrations use conflict-safe/create-if-missing patterns for bootstrap and are rerunnable.

## ChatGPT finance bridge

Protected routes:

- `GET /v1/gpt/status`
- `POST /v1/gpt/finance-transactions`
- `GET /v1/gpt/finance-transactions`
- `PATCH /v1/gpt/finance-transactions/{transaction_id}`

Action schema:

Use the single live schema below for the complete Operations + Accountant GPTS. It preserves the v0.17.2 operations actions and adds the finance bridge plus final-PO WhatsApp retrieval:

`https://sppg-finance-gpt-site-production-5b7d.up.railway.app/v1/schema/chatgpt-sppg-v0180.json`

The older finance-only YAML remains a compatibility artifact and should not replace the unified GPTS action.

Create flow:

1. ChatGPT classifies the operator message using existing SPPG categories/manual truth.
2. A stable `source_ref` is sent with the exact raw operator text.
3. PostgreSQL records the transaction and idempotency/audit metadata.
4. The same transaction is synchronized into the existing Firestore path/schema used by `src/App.jsx`.
5. Raw chat text + parsed transaction JSON is archived to Drive when credentials/folder are configured.
6. Retry with the same request does not duplicate the PostgreSQL transaction.

For explicit manual classifications such as `Beban Profit`, the supplied category is preserved exactly and must not be replaced by an automatic guess.

## Frontend

Set:

`VITE_SPPG_CORE_API_URL=https://<backend-service-domain>`

Do not put `DATABASE_URL`, service-account JSON, or `SPPG_GPT_API_KEY` in Vite/frontend variables.

## Safety gates

- Generic parser candidate events still enter staging/review first.
- Payment/approval/BGN/settlement workflow events require review.
- The authenticated ChatGPT finance bridge is a separate trusted-operator path for explicit finance instructions.
- ChatGPT must never invent amounts or infer `LUNAS` without explicit operator evidence/instruction.
- Existing calculator planning data remains independent from `po_qty`, received quantities, actual usage, and payments.

## Go-live validation

1. Backend deploy succeeds and `/health` loads.
2. PostgreSQL attached; `/health` shows `databaseReady=true`.
3. `SPPG_GPT_API_KEY` configured.
4. Google service account configured and shared to Drive root.
5. `GET /v1/gpt/status` confirms DB + Google + raw-chat folder configured.
6. Create one low-risk test transaction in Maja.
7. Confirm it appears in both PostgreSQL mirror and the existing Maja Firestore UI.
8. Retry the same request and confirm no duplicate transaction.
9. Search it through the GPT bridge.
10. Patch/correct it and confirm Firestore UI updates.
11. Configure one ChatGPT Action from `/v1/schema/chatgpt-sppg-v0180.json` and use the same bearer secret.
12. Only after these checks use chat for live operational finance entry.
