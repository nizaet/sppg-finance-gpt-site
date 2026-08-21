import importlib.util
from pathlib import Path

from backend.inventory_api import router as inventory_router
from backend.stock_opname_learning_patch import learned_parse_stock_opname_text


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


def test_dashboard_stock_format_reads_date_zeroes_and_local_package_units():
    result = parser.parse_stock_opname_text(
        """so 14 agustus 2026
*#_DASHBOARD STOK DAPUR_#*
• BAKING POWDER = *0*
• PEMASAK KAMBING = *6 BALL*
• KALDU JAMUR TOTOLE = *6 BUNGKUS*
• KECAP MANIS @5,7 KG = *1 DRIGENT*
• KETUMBAR @500 GR = *11 PAK*
• BERAS = *2 KARUNG*"""
    )

    by_name = {item["itemName"]: item for item in result["items"]}
    assert result["detectedStockDate"] == "2026-08-14"
    assert by_name["BAKING POWDER"]["qty"] == 0.0
    assert by_name["PEMASAK KAMBING"]["unit"] == "ball"
    assert by_name["KALDU JAMUR TOTOLE"]["unit"] == "bungkus"
    assert by_name["KECAP MANIS @5,7 KG"]["unit"] == "jerigen"
    assert by_name["KETUMBAR @500 GR"]["unit"] == "pack"
    assert by_name["BERAS"]["unit"] == "karung"


def test_stock_opname_history_exposes_detail_for_safe_correction():
    paths = {route.path for route in inventory_router.routes}
    assert "/v1/inventory/stock-opnames/{stock_opname_id}" in paths
    assert any(
        route.path == "/v1/inventory/stock-opnames/{stock_opname_id}" and "DELETE" in route.methods
        for route in inventory_router.routes
    )


def test_confirmed_oil_packages_merge_dus_pcs_and_liters():
    result = learned_parse_stock_opname_text(
        """1. Minyak Goreng: 2 dus
2. Minyak Goreng: 7 pcs
3. Minyak Goreng: 3 liter"""
    )

    oil = [item for item in result["items"] if item["normalizedItemName"] == "minyak goreng"]
    assert len(oil) == 1
    assert oil[0]["qty"] == 41.0
    assert oil[0]["unit"] == "liter"
    assert any("1 dus = 12 liter" in warning for warning in oil[0]["warnings"])
    assert any("1 pcs = 2 liter" in warning for warning in oil[0]["warnings"])
