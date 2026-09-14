from backend.inventory_unit_conversion import convert_inventory_quantity
from backend.item_taxonomy import stock_type


def test_unconfigured_package_never_guesses_weight_or_volume():
    qty, unit, note = convert_inventory_quantity(2, "botol", {"baseUnit": "liter", "metadata": {}})
    assert (qty, unit, note) == (2.0, "botol", None)


def test_confirmed_package_factor_converts_to_master_base_unit():
    qty, unit, note = convert_inventory_quantity(
        2,
        "botol",
        {"baseUnit": "liter", "metadata": {"unit_conversions": {"botol": 0.135}}},
    )
    assert qty == 0.27
    assert unit == "liter"
    assert note == "1 botol = 0.135 liter"


def test_same_unit_does_not_apply_package_factor_twice():
    qty, unit, note = convert_inventory_quantity(
        2,
        "liter",
        {"baseUnit": "liter", "metadata": {"unit_conversions": {"botol": 0.135}}},
    )
    assert (qty, unit, note) == (2.0, "liter", None)


def test_saori_oyster_sauce_uses_same_stock_type_as_saus_tiram():
    assert stock_type("Saus tiram Saori")["code"] == "SAUS_TIRAM"
    assert stock_type("Saus Tiram")["code"] == "SAUS_TIRAM"


def test_owner_confirmed_ladaku_piece_is_one_kilogram():
    qty, unit, note = convert_inventory_quantity(1, "pcs", {"stockTypeCode": "LADA_PUTIH"})
    assert (qty, unit) == (1.0, "kg")
    assert note == "1 pcs = 1 kg (aturan operasional)"


def test_owner_confirmed_saori_bottle_and_legacy_liter_are_kilograms():
    bottle = convert_inventory_quantity(2, "botol", {"stockTypeCode": "SAUS_TIRAM"})
    legacy = convert_inventory_quantity(2, "liter", {"stockTypeCode": "SAUS_TIRAM"})
    assert bottle[:2] == (2.0, "kg")
    assert legacy[:2] == (2.0, "kg")
