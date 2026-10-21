# PO Reminder and Kitchen Warehouse Scope

PO reminders for **MAJA** and **CEMPLANG** read only the warehouse of the selected kitchen. Koperasi stock is not silently added to either kitchen: it becomes usable only after a recorded internal transfer.

Rules:

- An exact, unit-compatible stock identity can reduce a PO need. A current warehouse balance already included in the planning projection is never deducted a second time.
- A similar name is only a reference for the operator. It does not hide a PO reminder automatically.
- The stock-check dialog shows the closest same-kitchen references, their actual balance, and their projected availability. The operator may select one to count it or enter a new physical total.
- The normal reminder queue does not run a second warehouse projection merely to prepare those references. References are loaded once, on demand, when the operator opens **Cek stok gudang**. The queue remains authoritative because its first projection has already deducted selected-kitchen stock.
- Saving a stock check writes only an auditable inventory correction. The reminder is recalculated and closes only if the resulting stock actually covers the requirement; it is not closed by an override merely because a check was entered.
- Immediately before a stock correction is saved, current exact PO coverage is checked again. An item already covered by a saved PO cannot change warehouse stock from a stale browser dialog.
- Adding warehouse stock first resolves or creates an inventory master item. The operator can select an existing master/category or type a new item/category. This does not rewrite a stock-opname, PO, receiving, or financial history.

Operational performance:

- The action queue covers overdue items from the previous seven days, today, and tomorrow; it is not a 21-day forecast.
- Projection reads use a short, per-site/per-date single-flight cache. The production site-only cooking-day projection must remain behind this cache when the server starts.
- A reminder refresh preserves MAJA/CEMPLANG isolation and never borrows stock from the other kitchen.

Related: [Koperasi Dry-Goods Flow](koperasi-flow.md), [SPPG Maja](../sites/maja.md), [SPPG Cemplang](../sites/cemplang.md).

## PO planning stock edits — operator correction, 2026-10-20

The stock input in the pulled daily PO working set was a browser-only override. The operator explicitly requires that saving it updates the kitchen warehouse and the purchase recommendation together.

- Typing a value stages a physical total. **Simpan stok & hitung PO** confirms and saves an audited warehouse delta, reloads the server projection for the selected cooking day, and recalculates purchase quantities for every affected ingredient line. Unrelated manual purchase edits remain.
- This PO-screen count is explicitly **before cooking**. It supersedes older estimates, but today's cooking still consumes it when preparing a PO for cooking tomorrow. Example: 15 kg physical − 4 kg today's cooking = 11 kg available; 12 kg tomorrow's requirement produces a 1 kg PO. A PO for cooking today does not subtract its own requirement before calculating its purchase need.
- This narrows the previous assumption that all per-item manual recounts already reflect the check day's consumption. Ordinary warehouse/reminder recounts keep their existing after-cooking semantics; only the explicit PO-planning correction carries `BEFORE_COOKING` evidence. Actual usage must never be deducted twice.
- Physical SO and source evidence remain immutable. A newer SO remains the physical anchor. Changes are kitchen-specific, reject stale physical balances or replaced planning, and are idempotent by request ID. Pending stock edits and failed projection refreshes block PO creation; refreshing after an acknowledged stock save does not write stock again.
- Existing saved PO quantities require their normal explicit edit/revision. This workflow recalculates the planning working set; it never silently revises an order already sent to a vendor. Pulled multi-date working sets must be refreshed after a stock correction.
- Cooking dates use Asia/Jakarta when deriving SQL dates from timestamps; 03:00 WIB is not the preceding UTC calendar date.
- Confirmed master aliases are carried to the PO matcher, with one allocation per physical stock identity. Operator shorthand **Jeruk ↔ Jeruk Medan** is recognized in both directions and grouped as one orange stock identity. Jeruk Nipis, Jeruk Lemon, Jeruk Bali and Daun Jeruk remain distinct. Other shorthand needs a confirmed master alias rather than broad substring/fuzzy merging.

Evidence: operator bug report in APP OPERASIONAL SPPG, 2026-10-20; `tests/po-warehouse-stock-ui.test.cjs`, `tests/test_po_warehouse_stock.py`, `tests/po-stock-matching.test.cjs`, and `tests/test_inventory_physical_projection.py`. Related: [receiving corrections](goods-receipt-corrections.md), [Koperasi flow](koperasi-flow.md).

## Pantry ingredient identity — operator correction, 2026-10-21

- **Gula**, **Gula Putih**, **Gula Pasir**, and branded white sugar such as **Gula Pasir Gulaku/Gmp** share the white-sugar stock type. Brown/palm/icing/liquid sugars remain separate. Brands qualify the saved display name; they do not prevent a known interchangeable ingredient from matching warehouse stock or saved PO coverage.
- **Garam Refina ↔ Garam**, **Kecap Asin Hati Angsa ↔ Kecap Asin**, and **Saus Tiram Saori ↔ Saus Tiram** share their respective ingredient identities. Kecap Manis and Kecap Jamur remain distinct from Kecap Asin.
- **Kaldu Jamur/Totole**, **Jamur**, **Jamur Kuping**, **Jamur Tiram**, and **Kecap Jamur** are separate identities. A broad substring, recipe note, stale planning identifier or contradictory alias must not substitute a different known ingredient.
- Saved PO detection uses actual saved item references for the selected site/vendor/date, with compatible units. A new planning snapshot or added brand does not make an already ordered ingredient new. Canceled orders and zero-quantity lines do not provide coverage.
- Read-only inspection of MAJA KOPERASI PO **#457**, distribution 2026-10-21, confirms a real Kaldu Jamur Totole line: its “sudah PO” badge is legitimate and must remain. The same order also contains Garam, Kecap Asin and Saus Tiram; their branded planning names must not invite duplicate orders.
- Ingredient equivalence does not establish packaging size. **Kaldu Jamur 5 bungkus** remains visible as unconverted stock against planning in **pack** until the bungkus-to-pack ratio is confirmed. The existing pouch-to-pack rule does not prove that every bungkus has the same contents.
- Preserve the latest SO, prior cooking depletion and one allocation per physical balance. This correction changes matching, not production SO, quantities, receiving, sent POs or payments.

Evidence: operator report and scoped read-only master/PO audit, 2026-10-21; shared `tests/fixtures/pantry-identities.json`, `tests/test_pantry_canonical_identity.py`, and production-transformed `tests/po-stock-matching.test.cjs`.
