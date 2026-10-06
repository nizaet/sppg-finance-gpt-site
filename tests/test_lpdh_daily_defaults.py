import unittest
from backend.lpdh_logic import normalize_daily_draft

class DailyDefaultsTests(unittest.TestCase):
    def test_site_defaults_only_fill_missing_choices(self):
        master={'dailyDefaults':{'incentiveEligibility':{'contamination':'Tidak','fatalIncident':'Tidak','suspended':'Tidak','verified':'Ya','pmInputSipgn':'Ya'},'bankBalance':999,'evidenceLink':'https://old.example'}}
        original={'incentive':{'eligibility':{'contamination':'Ya','verified':False}},'balance':{'bankBalance':123}}
        result=normalize_daily_draft(master,original)
        self.assertEqual(result['incentive']['eligibility']['contamination'],'Ya')
        self.assertEqual(result['incentive']['eligibility']['verified'],False)
        self.assertEqual(result['incentive']['eligibility']['fatalIncident'],'Tidak')
        self.assertEqual(result['balance']['bankBalance'],123)
        self.assertNotIn('evidenceLink',result['incentive'])
        self.assertEqual(original['incentive']['eligibility'],{'contamination':'Ya','verified':False})
        self.assertEqual(normalize_daily_draft(master,original,'GENERATED')['incentive'],original['incentive'])
        self.assertEqual(normalize_daily_draft({}, {})['incentive']['eligibility'],{})
