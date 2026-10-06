# SPPG Plugin MCP

Remote read-only MCP gateway for the SPPG operational application.

## Safety model

- Separate Railway service from the production web/API service.
- Same repository and domain logic imports, so there is no second PO/SO/payable calculation engine.
- No write tools are registered in the initial rollout.
- Receiving preview strips the operational confirmation token.
- SO and payable payloads force `commit=False`.
- `/health` is public for Railway health checks.
- `/mcp` requires `Authorization: Bearer <SPPG_MCP_API_KEY>`.

## Tools

1. `po_action_queue`
2. `receiving_preview`
3. `stock_opname_preview`
4. `vendor_invoice_parse_preview`
5. `vendor_payable_preview`
6. `vendor_payables_list`

## Run

```bash
export DATABASE_URL='...'
export SPPG_GPT_API_KEY='...'   # used by existing receiving guard helpers
export SPPG_MCP_API_KEY='...'
uvicorn plugin_mcp.server:app --host 0.0.0.0 --port 8000
```

MCP endpoint: `/mcp`

Health endpoint: `/health`
