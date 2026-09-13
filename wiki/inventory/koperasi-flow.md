# Koperasi Dry-Goods Flow

Indogrosir -> Koperasi -> Mungki -> Maja/Cemplang.

Rules:
- Purchase from Indogrosir = procurement into Koperasi inventory.
- Mungki dispatch to kitchen = internal stock transfer/fulfillment.
- Do not create a second purchase expense when stock is dispatched from Koperasi to a kitchen.
- Kitchen receipt should reduce Koperasi stock and increase destination stock through stock movements.
- Koperasi stock is not treated as MAJA/CEMPLANG stock in PO reminders. It is available to a kitchen only after the internal transfer is recorded; see [PO Reminder and Kitchen Warehouse Scope](po-reminder-stock-scope.md).
