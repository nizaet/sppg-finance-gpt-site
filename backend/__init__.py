"""SPPG backend route bundle.

`backend.app` mounts `operational_router` as the stable /v1 route bundle. Newer
subrouters are attached here so app.py does not need to be rewritten every time
a safe operational module is added.
"""

from backend.operational_api import router as operational_router
from backend.vendor_payables_api import router as vendor_payables_router
from backend.inventory_api import router as inventory_router
from backend.chat_api import router as chat_router
from backend.operational_history_api import router as operational_history_router
from backend.operational_search_api import router as operational_search_router
from backend.operations_action_schema_api import router as operations_schema_router
from backend.operations_action_schema_fix_api import router as operations_schema_fix_router
from backend.operations_action_schema_v017_api import router as operations_schema_v017_router
from backend.whatsapp_webhook_api import router as whatsapp_router

# Core domain + chat ingest. chat_router already contains domain_router, therefore
# mounting it here restores /v1/parse-message, /v1/goods-receipts,
# /v1/accountant-flow, /v1/bgn-flow, /v1/audit-log, and related domain routes.
operational_router.include_router(chat_router)

# Operational history/search and ChatGPT Action schemas.
operational_router.include_router(operational_history_router)
operational_router.include_router(operational_search_router)
operational_router.include_router(operations_schema_router)
operational_router.include_router(operations_schema_fix_router)
operational_router.include_router(operations_schema_v017_router)

# WhatsApp ingress uses its own /whatsapp prefix; nested under operational_router
# it becomes /v1/whatsapp/* as expected by the deployed callback contract.
operational_router.include_router(whatsapp_router)

# Payables/inventory remain part of the same operational bundle. app.py also
# exposes legacy aliases; keeping these nested routes preserves existing clients.
operational_router.include_router(vendor_payables_router)
operational_router.include_router(inventory_router)
