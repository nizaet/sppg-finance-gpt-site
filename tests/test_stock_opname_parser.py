import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "stock_opname_parser",
    Path(__file__).resolve().parents[1] / "backend" / "stock_opname_parser.py",
)
parser = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(parser)


def test_cemplang_so_preserves_mixed_units_duplicates_and_protein_weight():
    result = parser.parse_stock_opname_text(
        """*SO BARANG*
tgl 14 Agustus 2026
*GUDANG KERING*
1. tepung beras : 8 pcs + 0,40 ons
2. bawang merah : 7,26 kg
3. beras : 4 karung + 10,20
4. bawang merah : 14,14 kg
*GUDANG BASAH*
1. daun jeruk : 0,32
Ayam fillet:15 kantong
Berat:30 kg
Ayam potong:
Berat:54,76 kg
Ikan Dori:3 kantong"""
    )

    assert result["detectedStockDate"] == "2026-08-14"
    assert any(x["itemName"] == "tepung beras" and x["unit"] == "pcs" and x["qty"] == 8 for x in result["items"])
    assert any(x["itemName"] == "tepung beras" and x["unit"] == "ons" and x["qty"] == 0.4 for x in result["items"])
    assert any(x["itemName"] == "beras" and x["unit"] == "" and x["parseStatus"] == "REVIEW" for x in result["items"])
    assert any("Duplikat bawang merah" in warning for warning in result["warnings"])
    assert any(x["itemName"] == "Ayam fillet" and x["unit"] == "kg" and x["qty"] == 30 for x in result["items"])
    assert any(x["itemName"] == "Ayam potong" and x["unit"] == "kg" and x["qty"] == 54.76 for x in result["items"])


def test_dimensions_are_item_identity_and_unit_is_a_valid_stock_unit():
    result = parser.parse_stock_opname_text(
        """*KANTOR*
1. plastik item UK 90x120 : 1 unit
2. plastik item UK 90x100 : 1 pack"""
    )

    assert [(item["itemName"], item["qty"], item["unit"], item["parseStatus"]) for item in result["items"]] == [
        ("plastik item UK 90x120", 1.0, "unit", "READY"),
        ("plastik item UK 90x100", 1.0, "pack", "READY"),
    ]
