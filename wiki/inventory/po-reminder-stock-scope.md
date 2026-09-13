# PO Reminder and Kitchen Warehouse Scope

PO reminders for **MAJA** and **CEMPLANG** read only the warehouse of the selected kitchen. Koperasi stock is not silently added to either kitchen: it becomes usable only after a recorded internal transfer.

Rules:

- An exact, unit-compatible stock identity can reduce a PO need. A current warehouse balance already included in the planning projection is never deducted a second time.
- A similar name is only a reference for the operator. It does not hide a PO reminder automatically.
- The stock-check dialog shows the closest same-kitchen references, their actual balance, and their projected availability. The operator may select one to count it or enter a new physical total.
- Saving a stock check writes only an auditable inventory correction. The reminder is recalculated and closes only if the resulting stock actually covers the requirement; it is not closed by an override merely because a check was entered.
- Adding warehouse stock first resolves or creates an inventory master item. The operator can select an existing master/category or type a new item/category. This does not rewrite a stock-opname, PO, receiving, or financial history.

Related: [Koperasi Dry-Goods Flow](koperasi-flow.md), [SPPG Maja](../sites/maja.md), [SPPG Cemplang](../sites/cemplang.md).
