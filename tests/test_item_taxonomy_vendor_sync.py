import unittest

from backend.item_taxonomy import item_family, vendor_for_item


class MilkVendorTaxonomyRegressionTest(unittest.TestCase):
    def test_susu_clevo_ignores_stale_fish_category_and_vendor(self):
        name = "Susu Clevo 115ml Full Cream"
        self.assertEqual("DRY_GOODS", item_family(name, "IKAN"))
        self.assertEqual(
            "KOPERASI",
            vendor_for_item(name, "IKAN", "CEMPLANG", "RUMAH_DUTA_PANGAN"),
        )

    def test_generic_milk_is_koperasi(self):
        self.assertEqual("KOPERASI", vendor_for_item("Milk Life 200 ml", None, "MAJA", None))


if __name__ == "__main__":
    unittest.main()
