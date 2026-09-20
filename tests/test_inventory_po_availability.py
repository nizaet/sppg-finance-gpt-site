from backend.inventory_projection_v2_api import _available_for_next_po


def test_unreceived_po_does_not_offset_already_consumed_physical_stock():
    # 4 kg is on hand, 6 kg is used for today's cooking, and 5 kg is still
    # expected from an eligible PO. The future PO can use the incoming 5 kg;
    # it must not turn the two-kilo physical shortage into fictitious credit.
    assert _available_for_next_po(4, 6, 5) == 5


def test_remaining_physical_stock_and_expected_po_both_cover_future_plan():
    assert _available_for_next_po(5, 4, 3) == 4
