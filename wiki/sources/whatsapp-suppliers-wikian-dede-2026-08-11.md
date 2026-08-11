# WhatsApp Supplier Learning — Wikian & Dede — 2026-08-11

## Raw sources
- Wikian ZIP — Google Drive file id: `1baromLXCE3wUhl4_XBRBvRrli6rFI7DH`
- Dede Beras ZIP — Google Drive file id: `1rDzLVAteegKgUbnBTULkzd-b-wbO_-6h`

## Wikian / chicken
Observed durable patterns:
- PO can be sent as image or text and may contain several use dates/delivery dates.
- Orders are frequently revised after stock checks; quantity changes after initial order are normal.
- Delivery confirmation is conversational: requested delivery time, `udah jalan`, and explicit arrival confirmation.
- Product attributes matter operationally: fillet dada/paha, skin/no-skin, frozen/fresh, ground chicken.
- Quality issues can trigger return/replacement requests and must be a distinct workflow from ordinary receipt.
- A supplier acknowledgement such as `OK` is evidence of order/revision receipt but is not payment evidence.

Suggested events:
- `PO_SENT`
- `PO_REVISION`
- `PO_ACKNOWLEDGED`
- `DELIVERY_SCHEDULE_CONFIRMED`
- `GOODS_IN_TRANSIT`
- `GOODS_RECEIVED`
- `QUALITY_ISSUE_REPORTED`
- `RETURN_REPLACEMENT_REQUESTED`

## Dede / rice
Observed durable patterns:
- PO can include item, quantity, use date and an aggregated total quantity.
- Delivery schedule may be negotiated after PO, and supplier may prefer bulk delivery rather than daily delivery.
- Actual delivered quantity can differ from the originally discussed quantity; the final received quantity must be recorded separately from ordered quantity.
- Supplier payment requests occur in chat and can refer to prior deliveries.
- Transfer/payment proof is separate evidence and must not be inferred merely from a request to transfer.
- Price changes are communicated conversationally and should create a supplier-price observation/effective-price event rather than overwrite old prices.

Suggested events:
- `PO_SENT`
- `DELIVERY_PLAN_CHANGED`
- `GOODS_RECEIVED`
- `RECEIVED_QTY_RECONCILED`
- `VENDOR_PAYMENT_REQUESTED`
- `VENDOR_PAYMENT_CONFIRMED`
- `VENDOR_PRICE_CHANGED`

## Confidence
- Workflow patterns above: HIGH — repeatedly observed in the exported chats.
- Specific historical prices, dates, and quantities are evidence records, not permanent supplier master rules.
