from backend.inventory_projection_v2_api import _available_for_next_po


def test_unreceived_po_never_counts_as_physical_stock():
    # 4 kg is on hand, 6 kg is used for earlier cooking, and 5 kg is only on
    # an outstanding PO. The missing receipt must not create stock credit.
    assert _available_for_next_po(4, 6, 5) == 0


def test_remaining_physical_stock_ignores_unreceived_po_supply():
    assert _available_for_next_po(5, 4, 3) == 1
