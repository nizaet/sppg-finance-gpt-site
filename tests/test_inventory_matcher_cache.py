import unittest
from unittest.mock import patch
import test_generated_document_api
from backend import inventory_api as api

class MatcherCacheTests(unittest.TestCase):
    def masters(self, name='Beras'):
        return [{'code':'RICE','canonical_name':name,'normalized_canonical_name':name.lower(),'aliases':['beras putih'],
            'source_type':'INVENTORY_MASTER','priority':100,'source_refs':['inventory:RICE'],'base_unit':'kg','category_code':'BAHAN','metadata':{}}]

    def test_repeated_names_classified_once_and_results_are_isolated(self):
        masters=api.RequestItemMatchers(self.masters())
        with patch.object(api,'_classify_item',wraps=api._classify_item) as classify:
            first=api.classify_item('Beras',masters);first['knownAliases'].append('mutated')
            for _ in range(100):self.assertNotIn('mutated',api.classify_item('Beras',masters)['knownAliases'])
            self.assertEqual(classify.call_count,1)

    def test_exact_alias_contained_ambiguous_and_unmapped_match_original(self):
        for name in ['Beras','beras putih','Beras premium 5 kg','Mi telur','unknown', '']:
            original=self.masters();cached=api.RequestItemMatchers(self.masters())
            self.assertEqual(api.classify_item(name,original),api.classify_item(name,cached))
        original=self.masters()+[{**self.masters()[0],'code':'OTHER'}]
        self.assertEqual(api.classify_item('Beras',original),api.classify_item('Beras',api.RequestItemMatchers(original)))

    def test_new_snapshot_does_not_reuse_other_site_or_old_master(self):
        self.assertEqual(api.classify_item('Beras',api.RequestItemMatchers(self.masters()))['canonicalItemName'],'Beras')
        self.assertEqual(api.classify_item('Beras',api.RequestItemMatchers(self.masters('Beras baru')))['classificationStatus'],'UNMAPPED')

    def test_regex_compiled_once_per_request_candidate(self):
        masters=api.RequestItemMatchers(self.masters())
        with patch.object(api.re,'compile',wraps=api.re.compile) as compile:
            self.assertTrue(api._candidate_contains('beras','beras premium',masters))
            self.assertTrue(api._candidate_contains('beras','beras medium',masters))
            self.assertEqual(compile.call_count,1)

    def test_distinct_item_names_do_not_reclassify_every_master_type(self):
        rows = self.masters() + [
            {**self.masters()[0], 'code':f'ITEM_{i}', 'canonical_name':f'Bahan {i}',
             'normalized_canonical_name':f'bahan {i}', 'aliases':[]}
            for i in range(80)
        ]
        names = ['Beras', 'Gula Putih', 'Kaldu Jamur Totole'] + [f'Nama baru {i}' for i in range(40)]
        masters = api.RequestItemMatchers(rows)
        with patch.object(api, 'stock_type', wraps=api.stock_type) as resolve:
            results = [api.classify_item(name, masters) for name in names]
            self.assertEqual(resolve.call_count, len(rows) + len(names),
                             'resolve each master once, not once per distinct input name')
            for name in names:
                api.classify_item(name, masters)
            self.assertEqual(resolve.call_count, len(rows) + len(names))
        self.assertEqual(results, [api.classify_item(name, rows) for name in names],
                         'memoization must not change canonical matches or ambiguity')

    def test_master_type_cache_does_not_survive_a_new_snapshot(self):
        old = api.RequestItemMatchers(self.masters())
        new = api.RequestItemMatchers(self.masters('Kaldu Jamur'))
        api.classify_item('Beras', old)
        self.assertEqual(new.master_stock_types, {})
        api.classify_item('Kaldu Jamur', new)
        self.assertEqual(old.master_stock_types['Beras']['code'], 'BERAS')
        self.assertEqual(new.master_stock_types['Kaldu Jamur']['code'], 'KALDU_JAMUR')

if __name__=='__main__':unittest.main()
