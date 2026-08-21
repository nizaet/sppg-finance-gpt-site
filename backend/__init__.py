"""SPPG backend package route bundle.

`backend.app` mounts `operational_router`. Attach only compatibility routes that
are not already mounted through `reference_router` or directly by app.py.
"""

from backend.operational_api import router as operational_router
from backend.vendor_payables_api import router as vendor_payables_router
from backend.inventory_api import router as inventory_router
from backend.chat_api import router as chat_router
from backend.control_tower_api import router as control_tower_router
from backend.inventory_summary_api import router as inventory_summary_router
from backend.auth_api import router as auth_router
from backend.knowledge_runtime_api import router as knowledge_runtime_router
from backend.hermes_knowledge_api import router as hermes_knowledge_router
from backend.accountant_excel_api import router as accountant_excel_router
from backend.accountant_status_api import router as accountant_status_router

# Public login/session endpoints live under /v1/auth. Login enforcement is only
# activated after Railway has all role passwords + auth secret.
operational_router.include_router(auth_router)
operational_router.include_router(knowledge_runtime_router)
operational_router.include_router(hermes_knowledge_router)

# chat_router contains the domain router, restoring these live routes under /v1:
# /parse-message, /goods-receipts, /actual-usage, /accountant-flow,
# /bgn-flow, /audit-log, and their corresponding write endpoints.
operational_router.include_router(chat_router)

# Read-only projections and owner-side accountant artifacts/workflow controls.
operational_router.include_router(control_tower_router)
operational_router.include_router(inventory_summary_router)
operational_router.include_router(accountant_excel_router)
operational_router.include_router(accountant_status_router)

# Preserve the legacy compatibility bundle used by existing clients.
operational_router.include_router(vendor_payables_router)
operational_router.include_router(inventory_router)
