import unittest
import test_generated_document_api  # Isolate optional cloud dependencies in local tests.
from backend.lpdh_balance_carry import carry_opening

class CarryTests(unittest.TestCase):
    def test_component_carry_without_movements(self):
        source={'balance':{},'topups':[],'incentive':{}}
        result=carry_opening(source,{'raw':231548418,'operational':63866180,'incentive':58971802},'2026-10-07')
        self.assertEqual(result['balance'],{'openingRaw':231548418,'openingOperational':63866180,'openingIncentive':58971802})
        self.assertEqual(sum(result['balance'].values()),354386400)
        self.assertEqual(result['topups'],[])
        self.assertEqual(result['incentive'],{})
        self.assertEqual(source['balance'],{})

    def test_manual_zero_and_negative_survive(self):
        result=carry_opening({'balance':{'openingRaw':0,'openingOperational':-123}},{'raw':100,'operational':200,'incentive':300},'2026-10-07')
        self.assertEqual(result['balance'],{'openingRaw':0,'openingOperational':-123,'openingIncentive':300})

    def test_next_day_chain(self):
        first=carry_opening({},dict(raw=100,operational=200,incentive=300),'2026-10-07')
        second=carry_opening({},dict(raw=first['balance']['openingRaw']-10,operational=180,incentive=250),'2026-10-08')
        self.assertEqual(second['balance']['openingRaw'],90)

if __name__=='__main__':unittest.main()

