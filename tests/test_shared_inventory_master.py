import unittest
from backend.shared_inventory_master import plan_mapping
class SharedMasterTests(unittest.TestCase):
 def test_shared_sources_create_once_and_preserve_existing(self):
  rows=[{'name':'Kacang Panjang','unit':'kg','source':'MAJA:PRICE'}, {'name':'Kacang Panjang','unit':'gr','source':'CEMPLANG:RECIPE'}]
  result=plan_mapping([],rows)
  self.assertEqual(len(result['creations']),1);self.assertEqual(result['creations'][0]['base_unit'],'kg')
  self.assertEqual(plan_mapping(result['creations'],rows)['creations'],[])
 def test_alias_brands_and_no_stock_type_collision(self):
  masters=[{'code':'G','canonical_name':'Gula Pasir','base_unit':'kg','active':True,'aliases':['Gula Putih']}]
  result=plan_mapping(masters,[{'name':'Gula Pasir Gulaku','unit':'kg'},{'name':'Gula Putih','unit':'kg'},{'name':'Kaldu Jamur Totole','unit':'pack'},{'name':'Jamur Kuping','unit':'kg'}])
  self.assertEqual(result['aliases'],[{'code':'G','alias':'Gula Pasir Gulaku'}]);self.assertEqual(len(result['creations']),2)
 def test_unknown_conflicting_units_and_inactive_are_never_guessed(self):
  result=plan_mapping([{'code':'OFF','canonical_name':'Garam','base_unit':'kg','active':False}], [{'name':'Menu Ayam','source':'GRAMASI'},{'name':'Saus Tomat','unit':'kg'},{'name':'Saus Tomat','unit':'liter'},{'name':'Garam','unit':'kg'}])
  self.assertFalse(result['creations']);self.assertEqual({r['reason'] for r in result['unresolved']},{'UNIT_REQUIRED','CONFLICTING_UNITS','INACTIVE_OR_UNIT_CONFLICT'})
 def test_alias_ownership_and_distinct_dry_chili(self):
  masters=[{'code':'C','canonical_name':'Cabai Merah','base_unit':'kg','active':True,'aliases':[]}]
  result=plan_mapping(masters,[{'name':'Cabai Merah Kering','unit':'kg'}]);self.assertEqual(len(result['creations']),1);self.assertFalse(result['aliases'])
