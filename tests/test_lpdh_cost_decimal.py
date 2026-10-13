import unittest
import test_generated_document_api
from backend.lpdh_logic import compute_preview,cost_limit_detail

class CostDecimalTests(unittest.TestCase):
    def preview(self, cost):
        masters={'parameters':{'rawSmall':9242.12,'rawLarge':9242.12,'cityIndex':1}}
        daily={'pm':{'rows':[{'code':'KS-01','distributed':1,'received':1}],
            'production':{'produced':1,'organoleptic':0,'retainedSample':0}},
            'rawMaterials':[{'name':'Beras','qty':1,'price':cost,'unit':'kg'}]}
        return compute_preview(masters,daily,'2026-10-13',True,{})

    def test_rounded_same_rupiah_still_shows_decimal_excess_and_remains_invalid(self):
        result=self.preview(9242.30);check=next(x for x in result['checks'] if x['no']=='11')
        self.assertEqual(check['status'],'PERIKSA');self.assertEqual(result['rawStatus'],'MELEBIHI PAGU')
        for text in ['Rp9.242,30','Rp9.242,12','Rp0,18/porsi']:self.assertIn(text,check['detail'])
        self.assertEqual(result['rawTotal'],9242.30)

    def test_equal_within_limit_and_existing_tolerance_remain_ok(self):
        for cost in (9242.12,9242.1,9242.12005):
            self.assertEqual(self.preview(cost)['rawStatus'],'DALAM PAGU')

    def test_tiny_excess_does_not_display_as_zero(self):
        self.assertIn('< Rp0,01/porsi',cost_limit_detail('Biaya/porsi',9242.121,9242.12,'porsi'))

if __name__=='__main__':unittest.main()
