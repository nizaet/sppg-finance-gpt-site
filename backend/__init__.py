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
from backend.inventory_projection_v2_api import router as inventory_projection_v2_router
from backend.auth_api import router as auth_router
from backend.accountant_excel_api import router as accountant_excel_router
from backend.accountant_status_api import router as accountant_status_router
from backend.vendor_rule_admin_api import router as vendor_rule_admin_router
from backend.calculator_planning_bridge_api import router as calculator_planning_bridge_router
from backend.po_cleanup_api import router as po_cleanup_router
from backend.po_delivery_alerts_api import router as po_delivery_alerts_router
from backend.po_reminder_action_api import router as po_reminder_action_router
from backend.po_reminder_v2_api import router as po_reminder_v2_router
from backend.po_reminder_v3_api import router as po_reminder_v3_router
from backend.po_reminder_v4_api import router as po_reminder_v4_router
from backend.po_reminder_tools_api import router as po_reminder_tools_router
from backend.po_shortage_stock_api import router as po_shortage_stock_router
from backend.purchase_order_listing_api import router as purchase_order_listing_router
from backend.purchase_order_workflow_api import router as purchase_order_workflow_router
from backend.calculator_data_api import router as calculator_data_router
from backend.firebase_auth_api import router as firebase_auth_router

# Public login/session endpoints live under /v1/auth. Login enforcement is only
# activated after Railway has all role passwords + auth secret.
operational_router.include_router(auth_router)
operational_router.include_router(firebase_auth_router)

# chat_router contains the domain router, restoring these live routes under /v1:
# /parse-message, /goods-receipts, /actual-usage, /accountant-flow,
# /bgn-flow, /audit-log, and their corresponding write endpoints.
operational_router.include_router(chat_router)

# Read-only projections and owner-side workflow controls.
operational_router.include_router(control_tower_router)
operational_router.include_router(inventory_summary_router)
operational_router.include_router(inventory_projection_v2_router)
operational_router.include_router(accountant_excel_router)
operational_router.include_router(accountant_status_router)
operational_router.include_router(vendor_rule_admin_router)
operational_router.include_router(calculator_planning_bridge_router)

# Operational PO reads that are safe to add without changing PO source records.
operational_router.include_router(purchase_order_listing_router)
operational_router.include_router(po_delivery_alerts_router)

# v4 is the strict stock-aware reminder used by the current frontend. It only
# links a PO when distribution date + ingredient + unit + qty actually cover the
# requirement, and it keeps Tempe procurement rules separate from Tahu.
operational_router.include_router(po_reminder_v4_router)
operational_router.include_router(po_reminder_v3_router)
operational_router.include_router(po_reminder_tools_router)
operational_router.include_router(po_shortage_stock_router)
operational_router.include_router(po_reminder_action_router)
operational_router.include_router(po_reminder_v2_router)

# Register the guarded DELETE route before the legacy DRAFT-only DELETE route.
# FastAPI matches routes in registration order, so cancelled/test cleanup stays
# isolated without changing any other PO workflow endpoint.
operational_router.include_router(po_cleanup_router)
operational_router.include_router(purchase_order_workflow_router)
operational_router.include_router(calculator_data_router)

# Preserve the legacy compatibility bundle used by existing clients.
operational_router.include_router(vendor_payables_router)
operational_router.include_router(inventory_router)
