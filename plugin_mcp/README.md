# SPPG Operations MCP (read-only)

Remote MCP gateway for SPPG MAJA and CEMPLANG. It reuses the existing SPPG backend business rules and does not maintain a second calculation engine.

## Current status

The gateway is deployed on Railway and OAuth is wired to the existing **YAYASAN / OWNER** login in SPPG Core.

- MCP resource: `https://sppg-plugin-mcp-production.up.railway.app/mcp`
- Authentication: OAuth authorization code + PKCE S256
- SPPG identity: existing backend role `OWNER` (frontend label `YAYASAN`)
- OAuth subject: `SPPG_OWNER`
- Scope: `sppg:read`
- Access token lifetime: 1 hour
- Mode: read-only
- MAJA + CEMPLANG are available under the one OWNER identity.

The plugin does **not** create a new Firebase user. Firebase remains an application-side bridge where the existing SPPG application needs it.

Do not select **No Auth** in ChatGPT and do not paste SPPG API keys into plugin configuration.

## MCP tools

- `po_action_queue`: read PO requirements and coverage.
- `receiving_preview`: match incoming-goods text to PO without committing.
- `stock_opname_preview`: parse/normalize stock opname without saving.
- `vendor_invoice_parse_preview`: parse invoice text supplied in the call.
- `vendor_payable_preview`: calculate a draft payable with `commit=False`.
- `vendor_payables_list`: read existing vendor payables.

All six tools advertise MCP `readOnlyHint=true`, `destructiveHint=false`, and OAuth scope `sppg:read`.

## OAuth endpoints

- `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-authorization-server`
- `/authorize`
- `/token`
- `/register`
- `/mcp`

The authorization server accepts the stable ChatGPT callback and supports the ChatGPT client metadata client ID plus a restricted DCR fallback. Redirect URI, resource, scope, state and PKCE are validated.

The OWNER password is submitted only to the OAuth authorization page and is checked by the existing SPPG Core `/v1/auth/login` endpoint. It is never stored by the MCP service.

## Railway environment

Required variables:

- `SPPG_CORE_API_URL`
- `SPPG_OAUTH_ISSUER`
- `SPPG_OAUTH_AUDIENCE`
- `SPPG_OAUTH_RESOURCE_URL`
- `SPPG_OAUTH_ALLOWED_SUBJECTS=SPPG_OWNER`
- `SPPG_OAUTH_SCOPE=sppg:read`
- `SPPG_OAUTH_PRIVATE_KEY_B64`: legacy variable name currently used as high-entropy server-side token signing secret material.

`SPPG_OAUTH_JWKS_URL` remains configured for compatibility with the earlier resource-server design but access-token verification is local because the authorization server and resource server are the same service. No symmetric signing key is published.

## Tests and health

The Docker build runs the complete `plugin_mcp/test_*.py` suite. It covers OAuth configuration, token issue/validation round-trip, rejection of wrong subject/scope, discovery metadata, DCR callback restrictions, unauthenticated MCP challenge, authenticated MCP initialize and tool listing.

`/health` is not only a process liveness check. It also verifies OAuth configuration and an access-token issuance/validation round-trip. A broken OAuth configuration makes health return HTTP 503.

No production GPTS mutation/write flow is enabled by this gateway.
