# Single-owner ChatGPT MCP OAuth rollout

## Identity decision

SPPG already has the required identity model. The account shown in the frontend as **YAYASAN** is backend role `OWNER`; it is not a separate Firebase Authentication user.

The existing SPPG Core login endpoint authenticates `OWNER` using the Railway-managed OWNER password. The OWNER role already has MAJA + CEMPLANG operational access. The MCP OAuth authorization server therefore delegates password verification to SPPG Core instead of creating a second user/password store.

## Implemented flow

1. ChatGPT discovers protected-resource metadata from the MCP service.
2. ChatGPT discovers the authorization server on the same HTTPS origin.
3. Authorization request uses authorization code + PKCE S256, exact MCP `resource`, `state`, and scope `sppg:read`.
4. The user sees an SPPG Operations authorization page and enters the existing YAYASAN / OWNER password there.
5. The MCP authorization server calls SPPG Core `/v1/auth/login` with role `OWNER` and accepts only an OWNER response.
6. A short-lived one-time authorization code is stored only by its SHA-256 hash.
7. The token endpoint consumes the code once, checks client ID, exact callback, exact resource and PKCE verifier.
8. A one-hour audience-bound bearer access token is issued with subject `SPPG_OWNER` and scope `sppg:read`.
9. The MCP resource server validates issuer, audience, subject, expiry and scope before requests reach MCP.

No refresh token is issued in the initial rollout.

## ChatGPT client restrictions

Supported stable callback:

`https://chatgpt.com/connector_platform_oauth_redirect`

Supported client identification:
- ChatGPT client metadata document client ID: `https://chatgpt.com/oauth/client.json`
- restricted DCR fallback client ID issued by this server: `sppg-chatgpt-public-v1`

Arbitrary redirect URIs are rejected.

## Security gates in place

- HTTPS-only issuer/resource configuration.
- Fail closed when OAuth configuration is absent.
- PKCE S256 required.
- Exact MCP resource/audience binding.
- Exact stable ChatGPT callback allowlist.
- One-time authorization codes with five-minute maximum lifetime.
- Authorization codes stored by hash, not plaintext.
- Only `SPPG_OWNER` is accepted.
- Only `sppg:read` is required/granted.
- One-hour access tokens.
- OWNER password is verified by SPPG Core and is not retained by the MCP gateway.
- No SPPG API key is sent to ChatGPT.
- All MCP tools are explicitly read-only and destructive mutations are not exposed.
- Receiving confirmation tokens are removed from preview responses.
- Stock opname and payable preview force `commit=False`.

## Verification gates

Automated image-build tests cover:
- missing configuration fails closed;
- insecure OAuth URLs rejected;
- subject allowlist required;
- token issue/validation round-trip;
- wrong subject rejected;
- wrong scope rejected;
- OAuth protected-resource metadata;
- authorization-server metadata;
- restricted dynamic client registration;
- unauthenticated MCP returns OAuth bearer challenge;
- authenticated MCP initialize and tools/list;
- exact six-tool surface and read-only/security metadata.

Railway `/health` additionally performs a production-config OAuth token issue/validation round-trip. Health returns 503 if this fails.

A real-network Railway smoke job is used before ChatGPT connection to verify the public HTTPS routes and is deleted after the test.

## Rollout boundary

Keep the old GPTS and all production write workflows unchanged during this pilot.

Only after successful interactive ChatGPT OAuth connection and read-only calls to both MAJA and CEMPLANG should any later write-capable phase be designed. Write operations require a separate approval/confirmation design and are not part of this rollout.
