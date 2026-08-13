# Dynamic Vendor Master

Vendor configuration must be stored as data, not hard-coded application logic.

Recommended fields:
- id
- name
- categories
- sites
- WhatsApp/contact
- lead_time_days_before_cooking
- payment_term_type
- payment_term_detail
- payment_source
- via_entity_id
- internal_reimbursement flag
- bank account
- active/inactive
- notes

When a default vendor changes, historical PO/vendor references remain unchanged.
