# Costing

Keep quantity layers separate: planned_qty, po_qty, received_qty, actual_used_qty.
Keep price layers separate: planning_price, po_price, vendor_cost_price, claim_price.

Vendor invoice price is actual cost. Claim/reimbursement price is a separate business value. Never overwrite one with the other.
