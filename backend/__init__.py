"""SPPG backend package route bundle.

`backend.app` mounts `operational_router`. Attach only compatibility routes that
are not already mounted through `reference_router` or directly by app.py.
"""

from backend.operational_api import router as operational_router
from backend.vendor_payables_api import router as vendor_payables_router
from backend.inventory_api import router as inventory_router
from backend.chat_api import router as chat_router
from backend.control_tower_api import router as control_tower_router

# chat_router contains the domain router, restoring these live routes under /v1:
# /parse-message, /goods-receipts, /actual-usage, /accountant-flow,
# /bgn-flow, /audit-log, and their corresponding write endpoints.
operational_router.include_router(chat_router)

# Read-only v2 projection uses committed operational state instead of placeholder counters.
operational_router.include_router(control_tower_router)

# Preserve the legacy compatibility bundle used by existing clients.
operational_router.include_router(vendor_payables_router)
operational_router.include_router(inventory_router)
