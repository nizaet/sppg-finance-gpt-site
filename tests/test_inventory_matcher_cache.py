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

if __name__=='__main__':unittest.main()
