import unittest
from backend.lpdh_logic import merged_pm_rows


class DummyBastTests(unittest.TestCase):
    def test_dummy_counts_estimate_but_is_not_authentic(self):
        daily={'pm':{'rows':[{'code':'KS-01','received':100,'distributed':100,'bnba':'Ya','bastNo':'DRAFT-WAJIB-DIGANTI/2026-10-07/KS-01','bastLink':'https://example.invalid/BAST-DRAFT-WAJIB-DIGANTI'}]}}
        row=merged_pm_rows({},daily,True)[0]
        self.assertEqual(row['calculatedPm'],100)
        self.assertNotEqual(row['bastStatus'],'Terlampir')
        self.assertEqual(merged_pm_rows({},daily,False)[0]['calculatedPm'],0)
        daily['pm']['rows'][0].update(bastNo='BAST-ASLI-01',bastLink='https://drive.google.com/file/d/bukti/view')
        self.assertEqual(merged_pm_rows({},daily,True)[0]['bastStatus'],'Terlampir')
