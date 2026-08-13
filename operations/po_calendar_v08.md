# PO Calendar v0.8 — Cooking-Anchored Scheduling

## Anchor rule
PO lead time is calculated from **cooking start**, not distribution date.

Example:
- Distribution: Thursday
- Cooking: Wednesday night
- H-1 PO: Tuesday

## Initial known lead-time rules
- Sayur/buah (Holil): H-1 before cooking
- Tempe: H-2 before cooking
- Ayam (Wikian): H-3 before cooking

All lead times are vendor/item/site configurable and versioned. Historical PO due dates must retain the rule version used at creation.

## Required fields
- production_cycle_id
- site
- distribution_at
- cooking_start_at
- vendor_id
- category/item scope
- lead_time_value
- lead_time_unit
- lead_time_anchor = COOKING_START
- po_due_at
- planned_send_at
- actual_sent_at
- acknowledgement_at
- revision_count
- current_po_status
- rule_version

## Scheduling behavior
1. Read production cycle from calculator/planning layer.
2. Resolve cooking start.
3. Resolve vendor/item lead-time rule.
4. Calculate PO due time.
5. Group items by vendor/site/cycle.
6. Generate operational task.
7. Sending/revising PO creates events; it never rewrites planning data.

## Exceptions
- Urgent additions after PO are `PO_REVISION` or `PO_ADDITION`, linked to the active PO.
- Missing vendor acknowledgement creates a follow-up task, not a resend automatically.
- Vendor stock/price issue may create substitution/revision candidate requiring operator review.
- A changed future lead-time rule applies prospectively only.
