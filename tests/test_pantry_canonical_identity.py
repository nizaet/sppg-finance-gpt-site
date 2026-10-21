import json
from pathlib import Path

import pytest

from backend.inventory_api import classify_item
from backend.inventory_projection_v2_api import _type_key
from backend.item_taxonomy import stock_type


CASES = json.loads((Path(__file__).parent / "fixtures/pantry-identities.json").read_text())


def master(name, code=None, aliases=None):
    return {
        "code": code or name.upper().replace(" ", "_"),
        "canonical_name": name,
        "normalized_canonical_name": name.lower(),
        "aliases": aliases or [], "base_unit": "kg",
        "source_type": "INVENTORY_MASTER", "priority": 100,
    }


@pytest.mark.parametrize("name,code", CASES)
def test_pantry_identity_ignores_brand_but_preserves_ingredient(name, code):
    assert stock_type(name)["code"] == code


@pytest.mark.parametrize("name", ["Gula Merah", "Gula Aren", "Gula Jawa", "Gula Halus", "Gula Cair"])
def test_white_sugar_shorthand_never_merges_other_sugars(name):
    assert stock_type(name)["code"] != "GULA_PASIR"


def test_white_sugar_shorthand_resolves_verified_master_and_projection():
    masters = [master("Gula Pasir Gmp", aliases=["gula pasir"]), master("Gula Merah")]
    for name in ["Gula", "Gula Putih", "Gula Pasir Gulaku"]:
        match = classify_item(name, masters)
        assert match["inventoryItemCode"] == "GULA_PASIR_GMP"
        assert _type_key(name, "kg", masters)[:2] == ("GULA_PASIR", "kg")


@pytest.mark.parametrize("name,parent", [
    ("Kaldu Jamur Totole", "Jamur"),
    ("Kaldu Jamur", "Jamur Kuping"),
    ("Saus Tiram Saori", "Jamur Tiram"),
    ("Saus Tiram Saori", "Tiram"),
    ("Kecap Asin Hati angsa", "Kecap Jamur"),
    ("Bawang Putih Bubuk", "Bawang Putih"),
])
def test_specific_ingredient_rejects_wrong_parent_even_with_stale_exact_alias(name, parent):
    aliases = [name.lower()] if stock_type(parent)["method"] == "ITEM_TYPE_RULE" else []
    result = classify_item(name, [master(parent, aliases=aliases)])
    assert result["inventoryItemCode"] is None
    assert result["canonicalItemName"] == name


def test_same_type_multiple_masters_requires_review_instead_of_picking_brand():
    result = classify_item("Gula", [master("Gula Pasir Gmp"), master("Gula Pasir Gulaku")])
    assert result["classificationStatus"] == "AMBIGUOUS"
    assert result["inventoryItemCode"] is None
