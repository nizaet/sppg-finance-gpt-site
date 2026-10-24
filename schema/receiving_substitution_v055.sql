-- Preserve original PO quantities and prices. Actual replacement and PO credit are separate.
alter table goods_receipt_items add column if not exists replacement_item_code text;
alter table goods_receipt_items add column if not exists replacement_item_name text;
alter table goods_receipt_items add column if not exists replaces_qty numeric(18,4) check (replaces_qty > 0);
alter table goods_receipt_items add column if not exists replacement_vendor_cost_price numeric(18,4) check (replacement_vendor_cost_price >= 0);
alter table goods_receipt_items add constraint receiving_substitution_complete check (
 (replacement_item_code is null and replacement_item_name is null and replaces_qty is null)
 or (replacement_item_code is not null and replacement_item_name is not null and replaces_qty is not null)
);
