import unittest
from backend.lpdh_logic import compute_preview


class EmptyDayIncentiveTests(unittest.TestCase):
    def test_samples_do_not_create_pm_on_empty_day(self):
        daily = {'pm': {'production': {'organoleptic': 3, 'retainedSample': 2}}}
        preview = compute_preview({}, daily, '2026-10-08', True)
        self.assertEqual(preview['production']['incentivePm'], 0)

    def test_samples_remain_in_existing_received_day(self):
        daily = {'pm': {'production': {'organoleptic': 3, 'retainedSample': 2}, 'rows': [
            {'code': 'KS-01', 'received': 100, 'distributed': 100, 'bnba': 'Ya',
             'bastNo': 'DRAFT-WAJIB-DIGANTI/2026-10-08/KS-01',
             'bastLink': 'https://example.invalid/BAST-DRAFT-WAJIB-DIGANTI'}]}}
        preview = compute_preview({}, daily, '2026-10-08', True)
        self.assertEqual(preview['production']['incentivePm'], 105)

