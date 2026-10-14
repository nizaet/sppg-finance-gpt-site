# Single-owner ChatGPT MCP OAuth rollout

## Current status
- The MCP gateway validates RS256 JWTs against configured JWKS and denies access if not configured.
- This is an OAuth **resource server**, NOT an OAuth authorization server.
- Do not select No Auth in ChatGPT and do not expose the existing SPPG_MCP_API_KEY in ChatGPT UI.
- Deployment SUCCESS / health OK does not prove OAuth login or MCP tool calls work.

## Intended design
- ChatGPT -> OAuth Authorization Code + PKCE (S256) -> trusted identity authorization service.
- Authenticate the owner using existing Firebase Authentication (verify Firebase ID token on the server).
- Authorization service issues short-lived, audience-bound RS256 access JWT and publishes JWKS.
- Resource server enforces exact issuer, audience, subject allowlist, scope sppg:read and signature.
- No refresh tokens unless strictly necessary. Never log authorization codes, tokens, Firebase ID tokens or secrets.
- No new identity/password store.

## Required endpoints (authorization server)
- /.well-known/oauth-authorization-server (metadata)
- /authorize (state, client_id, redirect_uri, code_challenge, code_challenge_method=S256, scope, response_type=code)
- /token (one-time code exchange, enforce PKCE verifier and redirect_uri)
- /jwks.json
- Dynamic client registration if required by ChatGPT client registration behavior.

## Security gates
- Verify exact redirect URI against registered client, no wildcard redirects.
- CSRF state bound to browser session; short-lived one-time authorization codes.
- Store code hashes and PKCE challenge server-side with atomic consume and TTL.
- Verify Firebase ID token with Firebase Admin SDK; authorize only explicit owner UID.
- Verify scopes, resource/audience, expiry, issuer, signing key and revoked users.
- Rate-limit auth endpoints, secure cookies, TLS only, no token in query or logs.
- Test denial: missing token, wrong user, expired token, wrong audience, wrong scope, reused code, wrong verifier.
- Test success: login through ChatGPT, list tools, read PO/SO/receiving/payables, confirm zero DB mutations.
- Do not enable writes or migrate GPTS until all tests pass.

## Configuration still needed
- Firebase project ID and verified owner UID (never guess these).
- OAuth issuer hostname, resource URL and RS256 signing key stored as Railway secret.
- ChatGPT redirect URIs and registration mode verified during integration.
- Actual OAuth provider or implemented authorization server.

## Current fail-closed behavior
When OAuth configuration is missing, the MCP route returns 503. This is intentional and safer than exposing data. The health endpoint may still report OK because it only tests process liveness.
