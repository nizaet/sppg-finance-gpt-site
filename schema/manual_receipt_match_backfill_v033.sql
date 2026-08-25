-- Repair legacy GPT manual receipts that already point to an exact PO item but
-- were stored before receipt match metadata was populated.

update goods_receipt_items gri
set reported_item_name = coalesce(gri.reported_item_name, poi.item_name),
    po_qty_snapshot = coalesce(gri.po_qty_snapshot, poi.po_qty),
    variance_qty = coalesce(gri.variance_qty, gri.accepted_qty - poi.po_qty),
    match_confidence = case when coalesce(gri.match_confidence,0) = 0 then 1 else gri.match_confidence end,
    match_method = coalesce(gri.match_method, 'explicit_po_item_id_backfill'),
    updated_at = now()
from purchase_order_items poi, goods_receipts gr
where gri.purchase_order_item_id = poi.id
  and gri.goods_receipt_id = gr.id
  and poi.purchase_order_id = gr.purchase_order_id
  and upper(coalesce(gr.source_type,'MANUAL')) = 'MANUAL'
  and (
    gri.reported_item_name is null or gri.po_qty_snapshot is null or gri.variance_qty is null
    or coalesce(gri.match_confidence,0) = 0 or gri.match_method is null
  );

update goods_receipts gr
set match_status = 'CONFIRMED', match_confidence = 1,
    confirmed_at = coalesce(gr.confirmed_at,gr.received_at,now()), updated_at = now()
where upper(coalesce(gr.source_type,'MANUAL')) = 'MANUAL'
  and exists (select 1 from goods_receipt_items gri where gri.goods_receipt_id=gr.id)
  and not exists (
    select 1
    from goods_receipt_items gri
    left join purchase_order_items poi
      on poi.id=gri.purchase_order_item_id and poi.purchase_order_id=gr.purchase_order_id
    where gri.goods_receipt_id=gr.id and poi.id is null
  );

with receipt_totals as (
  select po.id as purchase_order_id,
         bool_and(coalesce(received.accepted_total,0) >= poi.po_qty) as complete,
         bool_or(coalesce(received.accepted_total,0) > 0) as any_received
  from purchase_orders po
  join purchase_order_items poi on poi.purchase_order_id=po.id
  left join (
    select purchase_order_item_id,sum(accepted_qty) as accepted_total
    from goods_receipt_items group by purchase_order_item_id
  ) received on received.purchase_order_item_id=poi.id
  where upper(po.status) in ('FINALIZED','SENT','ACKNOWLEDGED','PARTIAL_RECEIVED','RECEIVED')
  group by po.id
)
update purchase_orders po
set status = case when totals.complete then 'RECEIVED' else 'PARTIAL_RECEIVED' end,
    updated_at = now()
from receipt_totals totals
where po.id=totals.purchase_order_id and totals.any_received
  and po.status is distinct from case when totals.complete then 'RECEIVED' else 'PARTIAL_RECEIVED' end;
