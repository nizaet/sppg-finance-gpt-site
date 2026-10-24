# SPPG WhatsApp receiving bridge — initial connection trial

Independent Railway service in fearless-mindfulness; does not modify or restart Core/MCP. Deploy from the dedicated branch with service Dockerfile `/whatsapp_bridge/Dockerfile`; watch only `whatsapp_bridge/**`. Railway settings are applied directly to this service. The inherited root railway.json is deliberately absent on this branch so it cannot select the main application Dockerfile. One replica, sleep disabled, persistent Volume at `/data`.

Required server-only variables: `SPPG_CORE_API_URL` (existing SPPG Core), `SPPG_GPT_API_KEY` (Railway reference to Core, never expose in browser). UI login validates existing OWNER credentials through Core; session is Secure/HttpOnly/SameSite and mutation endpoints require same Origin. QR, account group roster and reports require OWNER. Public health exposes no account data.

Owner starts pairing, scans QR using a dedicated operational number, then explicitly maps up to one participating group to each kitchen. Only live `notify` message events from those exact group IDs are processed; history sync, outgoing messages and all other chats are excluded. No WhatsApp send API is exposed.

Incoming text/captions are durably stored in SQLite before forwarding to existing `/v1/whatsapp/ingest-normalized` with an exact kitchen source key. It stages candidate evidence only, never receipt/stock/payable commits. Same message IDs deduplicate; repeated content and edited bodies are held for manual review. Captionless images/PDFs remain manual review; no OCR or media download in this phase. Web-push is opt-in and subscription endpoints are restricted to major push hosts. Failed staging retries from durable outbox. Auth credentials and VAPID keys stay on the Volume; do not commit/export that directory.

Known trial limits: Baileys is unofficial; session/account restrictions and protocol changes can interrupt capture. Reports sent while disconnected are not guaranteed to replay; keep manual reporting until live tests pass. Revisions already staged in Core need human review there; no automated reversal. No stock confirmation is provided on the bridge UI: use existing SPPG receiving/Control Room confirmation. Notifications are on this bridge origin, not yet embedded into the main SPPG app. End-to-end verification requires owner QR pairing and selected groups.

Run `npm ci && npm test`. Health `/health`; control page `/`.
