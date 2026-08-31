from datetime import date

from backend.po_operational_policy_patch import (
    _merge_stock_rows,
    _resolve_procurement_rule,
    format_purchase_order_whatsapp,
)


def test_po_copy_uses_delivery_and_distribution_labels():
    po = {
        "site": "CEMPLANG",
        "po_code": "PO-CEMPLANG-20260902-HOLIL",
        "revision_no": 1,
        "distribution_date": date(2026, 9, 2),
        "coverage_dates": [date(2026, 9, 2)],
        "cooking_date": date(2026, 9, 1),
        "cooking_dates": [date(2026, 9, 1)],
        "scheduled_order_date": date(2026, 8, 31),
        "item_schedule": [
            {
                "item_name": "Bawang Putih",
                "cooking_date": date(2026, 9, 1),
                "scheduled_order_date": date(2026, 8, 31),
            }
        ],
        "items": [{"item_name": "Bawang Putih", "po_qty": 5, "unit": "kg"}],
    }
    text = format_purchase_order_whatsapp(po, "Holil")
    assert "Kirim PO" not in text
    assert "🚚 *Kirim Barang:* Selasa, 1 September 2026 (hari masak)" in text
    assert "📅 *Untuk Distribusi:* Rabu, 2 September 2026" in text


def test_protein_delivery_is_one_day_after_po_date():
    po = {
        "site": "MAJA",
        "po_code": "PO-MAJA-20260902-WIKIAN",
        "revision_no": 1,
        "distribution_date": date(2026, 9, 2),
        "coverage_dates": [date(2026, 9, 2)],
        "cooking_date": date(2026, 9, 1),
        "cooking_dates": [date(2026, 9, 1)],
        "scheduled_order_date": date(2026, 8, 30),
        "item_schedule": [
            {
                "item_name": "Ayam Fillet Dada",
                "cooking_date": date(2026, 9, 1),
                "scheduled_order_date": date(2026, 8, 30),
            }
        ],
        "items": [{"item_name": "Ayam Fillet Dada", "po_qty": 200, "unit": "kg"}],
    }
    text = format_purchase_order_whatsapp(po, "Wikian")
    assert "🚚 *Kirim Barang:* Senin, 31 Agustus 2026 (H+1 setelah PO untuk ayam/daging/ikan)" in text


def test_tahu_cemplang_ignores_stale_bahan_kering_category():
    rules = [
        {
            "id": 10,
            "vendor_code": "KOPERASI",
            "vendor_name": "Koperasi / Mungki",
            "site_code": "CEMPLANG",
            "category_code": "BAHAN_KERING",
            "lead_time_days_before_cooking": 1,
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
        },
        {
            "id": 11,
            "vendor_code": "HAJI_BADRI",
            "vendor_name": "Haji Badri",
            "site_code": "CEMPLANG",
            "category_code": "TAHU",
            "lead_time_days_before_cooking": 0,
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
        },
    ]
    row = {
        "site": "CEMPLANG",
        "item_name": "Tahu Cemplang",
        "category_code": "BAHAN_KERING",
        "preferred_vendor_code": "KOPERASI",
        "cooking_date": date(2026, 9, 1),
    }
    vendor, rule, bucket = _resolve_procurement_rule(rules, {"HAJI_BADRI": "Haji Badri"}, row)
    assert vendor == "HAJI_BADRI"
    assert rule["category_code"] == "TAHU"
    assert bucket == "TOFU"


def test_bawang_putih_uses_produce_rule_even_with_stale_koperasi_category():
    rules = [
        {
            "id": 20,
            "vendor_code": "KOPERASI",
            "vendor_name": "Koperasi / Mungki",
            "site_code": "CEMPLANG",
            "category_code": "BAHAN_KERING",
            "lead_time_days_before_cooking": 1,
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
        },
        {
            "id": 21,
            "vendor_code": "HOLIL",
            "vendor_name": "Holil",
            "site_code": "CEMPLANG",
            "category_code": "SAYUR_BUAH",
            "lead_time_days_before_cooking": 1,
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
        },
    ]
    row = {
        "site": "CEMPLANG",
        "item_name": "Bawang Putih",
        "category_code": "BAHAN_KERING",
        "preferred_vendor_code": "KOPERASI",
        "cooking_date": date(2026, 9, 1),
    }
    vendor, rule, _ = _resolve_procurement_rule(rules, {"HOLIL": "Holil"}, row)
    assert vendor == "HOLIL"
    assert rule["category_code"] == "SAYUR_BUAH"


def test_gudang_koperasi_stock_is_added_to_site_available_stock():
    site_rows = [{
        "item_name": "Bawang Putih",
        "unit": "kg",
        "available_for_po": 2,
        "balance": 2,
        "actual_balance": 2,
        "projected_balance": 2,
        "raw_item_names": ["Bawang Putih"],
        "area_codes": ["GUDANG_KERING"],
    }]
    warehouse_rows = [{
        "item_name": "Bawang Putih",
        "unit": "KG",
        "available_for_po": 8,
        "balance": 8,
        "actual_balance": 8,
        "projected_balance": 8,
        "raw_item_names": ["Bw Putih"],
        "area_codes": ["KOPERASI"],
    }]
    merged = _merge_stock_rows(site_rows, warehouse_rows)
    assert len(merged) == 1
    assert merged[0]["available_for_po"] == 10
    assert merged[0]["site_available_for_po"] == 2
    assert merged[0]["warehouse_available_for_po"] == 8
    assert "Bw Putih" in merged[0]["raw_item_names"]


def test_warehouse_only_bawang_putih_remains_visible_to_po_planner():
    merged = _merge_stock_rows([], [{
        "item_name": "Bawang Putih",
        "unit": "kg",
        "available_for_po": 6.3,
        "balance": 6.3,
        "actual_balance": 6.3,
        "projected_balance": 6.3,
        "raw_item_names": ["bawang putih", "bw putih"],
        "area_codes": ["KOPERASI"],
    }])
    assert len(merged) == 1
    assert merged[0]["available_for_po"] == 6.3
    assert merged[0]["warehouse_available_for_po"] == 6.3
    assert merged[0]["stock_basis"] == "GUDANG_KOPERASI_AVAILABLE_FOR_SITE_PO"
