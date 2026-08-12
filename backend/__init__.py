"""SPPG backend package route bundle.

The main app already mounts backend.operational_api.router.  Include newer
operational subrouters here so older app wiring remains backward compatible.
"""

from backend.operational_api import router as operational_router
from backend.vendor_payables_api import router as vendor_payables_router
from backend.inventory_api import router as inventory_router

operational_router.include_router(vendor_payables_router)
operational_router.include_router(inventory_router)
