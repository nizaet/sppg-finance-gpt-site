# SPPG Operations MCP (read-only)

Remote MCP gateway for MAJA and CEMPLANG. Uses existing backend business rules.

## Current status

The gateway is deployed on Railway. **OAuth login is not yet operational.**
The OAuth resource server verifies RS256 JWT access tokens, but requires a separately configured OAuth authorization server and owner allowlist. With missing configuration, `/mcp` returns HTTP 503 (fail closed). Railway `/health` only indicates process liveness.

Do not select **No Auth** in ChatGPT and do not paste the existing SPPG API key into plugin configuration.

## MCP tools

- `po_action_queue`: PO needs/coverage
- `receiving_preview`: match WhatsApp goods arrivals to PO without committing
- `stock_opname_preview`: normalize SO without saving
- `vendor_invoice_parse_preview`: parse supplied invoice text
- `vendor_payable_preview`: calculate draft payable without committing
- `vendor_payables_list`: inspect payables

## OAuth resource server environment

- `SPPG_OAUTH_ISSUER`: exact HTTPS token issuer
- `SPPG_OAUTH_AUDIENCE`: JWT audience for MCP
- `SPPG_OAUTH_JWKS_URL`: trusted HTTPS JWKS endpoint
- `SPPG_OAUTH_RESOURCE_URL`: exact public HTTPS MCP resource URL
- `SPPG_OAUTH_ALLOWED_SUBJECTS`: comma-separated explicit allowed subject IDs, initially just the owner
- `SPPG_OAUTH_SCOPE`: default `sppg:read`

Tokens require `exp`, `iat`, `iss`, `aud`, `sub`, valid RS256 signature, authorized subject and required scope.

See [OAUTH_ROLLOUT.md](OAUTH_ROLLOUT.md) for the outstanding authorization-server implementation and integration tests.

## Local

```bash
uvicorn plugin_mcp.server:app --host 0.0.0.0 --port 8000
```

Public health: `/health`. Protected MCP: `/mcp`.
