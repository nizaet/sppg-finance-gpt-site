from datetime import date

from backend.po_operational_policy_patch import _resolve_procurement_rule
from backend.po_schedule import _item_rule


def _rule(vendor, category, lead, rule_id):
    return {
        "id": rule_id,
        "vendor_code": vendor,
        "vendor_name": vendor.title(),
        "site_code": "CEMPLANG",
        "category_code": category,
        "lead_time_days_before_cooking": lead,
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
    }


def test_cemplang_tahu_is_badri_h1_even_when_legacy_rule_is_h4():
    vendor, rule, bucket = _resolve_procurement_rule(
        [_rule("HAJI_BADRI", "TAHU", 4, 1), _rule("KOPERASI", "BAHAN_KERING", 1, 2)],
        {"HAJI_BADRI": "Haji Badri"},
        {
            "site": "CEMPLANG",
            "item_name": "Tahu Putih",
            "category_code": "TEMPE_TAHU",
            "preferred_vendor_code": "KOPERASI",
            "cooking_date": date(2026, 9, 23),
        },
    )
    assert vendor == "HAJI_BADRI"
    assert bucket == "TOFU"
    assert rule["lead_time_days_before_cooking"] == 1


def test_gula_merah_is_holil_even_when_snapshot_prefers_koperasi():
    vendor, rule, _ = _resolve_procurement_rule(
        [_rule("KOPERASI", "BAHAN_KERING", 1, 1), _rule("HOLIL", "SAYUR_BUAH", 1, 2)],
        {"HOLIL": "Haji Holil"},
        {
            "site": "CEMPLANG",
            "item_name": "Gula Merah",
            "category_code": "BAHAN_KERING",
            "preferred_vendor_code": "KOPERASI",
            "cooking_date": date(2026, 9, 23),
        },
    )
    assert vendor == "HOLIL"
    assert rule["lead_time_days_before_cooking"] == 1


def test_saved_cemplang_tahu_schedule_does_not_use_legacy_h4():
    rule = _item_rule([_rule("HAJI_BADRI", "TAHU", 4, 1)], "HAJI_BADRI", "CEMPLANG", "Tahu Putih", date(2026, 9, 23))
    assert rule["lead_time_days_before_cooking"] == 1
