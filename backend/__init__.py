"""SPPG backend package route bundle.

`backend.app` mounts `operational_router`. Attach only compatibility routes that
are not already mounted through `reference_router` or directly by app.py.
"""

from backend.operational_api import router as operational_router
from backend.receiving_runtime_patch import install as install_receiving_runtime_patch
from backend.receiving_multi_po_runtime_patch import install as install_receiving_multi_po_runtime_patch
from backend.action_schema_runtime_patch import install as install_action_schema_runtime_patch

# Keep the existing WhatsApp parser improvements, then replace only the current
# receiving execution callable with deterministic multi-PO reconciliation.
install_receiving_runtime_patch()
install_receiving_multi_po_runtime_patch()

# Keep the stable v0.18.4 schema URL while enriching the callable before
# backend.app imports it for the public schema alias.
install_action_schema_runtime_patch()

from backend.vendor_payables_api import router as vendor_payables_router
from backend.vendor_payment_override_api import router as vendor_payment_override_router
from backend.vendor_payment_duplicate_guard_patch import install as install_vendor_payment_duplicate_guard_patch
from backend.inventory_api import router as inventory_router
from backend.inventory_manual_api import router as inventory_manual_router
from backend.chat_api import router as chat_router
from backend.control_tower_api import router as control_tower_router
from backend.inventory_summary_api import router as inventory_summary_router
from backend.inventory_projection_v2_api import router as inventory_projection_v2_router
from backend.auth_api import router as auth_router
from backend.accountant_bgn_flow_api import router as accountant_bgn_flow_router
from backend.accountant_excel_api import router as accountant_excel_router
from backend.accountant_excel_fail_safe_patch import install as install_accountant_excel_fail_safe_patch
from backend.accountant_selected_plan_api import router as accountant_selected_plan_router
from backend.accountant_status_api import router as accountant_status_router
from backend.vendor_rule_admin_api import router as vendor_rule_admin_router
from backend.calculator_ai_api import router as calculator_ai_router
from backend.calculator_planning_bridge_api import router as calculator_planning_bridge_router
from backend.goods_receipt_visibility_api import router as goods_receipt_visibility_router
from backend.po_cleanup_api import router as po_cleanup_router
from backend.po_delivery_alerts_api import router as po_delivery_alerts_router
from backend.po_receiving_confirmation_api import router as po_receiving_confirmation_router
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
from backend.knowledge_runtime_api import router as knowledge_runtime_router
from backend.po_reminder_projection_cache_patch import install as install_po_reminder_projection_cache_patch
from backend.po_delivery_receipt_reconcile_patch import install as install_po_delivery_receipt_reconcile_patch

# Excel bytes remain available even when Drive upload fails.
install_accountant_excel_fail_safe_patch()

# A retry of an already-paid-unreconciled transfer must remain unresolved until
# the dedicated reconciliation action links it to one invoice.
install_vendor_payment_duplicate_guard_patch()

# Reuse identical site/date stock projections for a few seconds. This only
# removes duplicate expensive reads; it does not change stock or PO arithmetic.
install_po_reminder_projection_cache_patch()

# Reconcile valid goods receipts that have the correct PO header but a missing
# purchase_order_item_id. Matching is constrained to that same PO and must be
# unambiguous before it can reduce a delivery alert.
install_po_delivery_receipt_reconcile_patch()

# Public login/session endpoints live under /v1/auth. Login enforcement is only
# activated after Railway has all role passwords + auth secret.
operational_router.include_router(auth_router)
operational_router.include_router(firebase_auth_router)

# /v1/gpt is public at middleware level, but this runtime endpoint itself
# requires the configured GPT bearer and returns canonical + live context.
operational_router.include_router(knowledge_runtime_router)

# Strict read-only flow routes are mounted before chat_router's legacy domain
# routes so partial/older Railway schemas do not make Accountant/BGN tabs fail.
operational_router.include_router(accountant_bgn_flow_router)

# chat_router contains the domain router, restoring these live routes under /v1:
# /parse-message, /goods-receipts, /actual-usage, legacy /accountant-flow,
# legacy /bgn-flow, /audit-log, and their corresponding write endpoints.
operational_router.include_router(chat_router)

# Read-only projections and owner-side workflow controls.
operational_router.include_router(control_tower_router)
operational_router.include_router(inventory_summary_router)
operational_router.include_router(inventory_projection_v2_router)
operational_router.include_router(accountant_excel_router)
operational_router.include_router(accountant_selected_plan_router)
operational_router.include_router(accountant_status_router)
operational_router.include_router(vendor_rule_admin_router)
operational_router.include_router(calculator_ai_router)
operational_router.include_router(calculator_planning_bridge_router)

# Operational PO/receiving reads that are safe to add without changing source records.
operational_router.include_router(purchase_order_listing_router)
operational_router.include_router(po_delivery_alerts_router)
operational_router.include_router(po_receiving_confirmation_router)
operational_router.include_router(goods_receipt_visibility_router)

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

# Preserve the legacy compatibility bundle used by existing clients, then add
# the non-destructive payment-evidence/reconciliation bridge alongside it.
operational_router.include_router(vendor_payables_router)
operational_router.include_router(vendor_payment_override_router)
operational_router.include_router(inventory_router)
operational_router.include_router(inventory_manual_router)