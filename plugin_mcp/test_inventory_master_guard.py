"""Master/alias regressions with an isolated in-memory DB adapter; no live writes."""
import ast
from copy import deepcopy
import json,re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from backend.inventory_master_guard import build_master_plan,snapshot_hash

def norm(value):return ' '.join(value.lower().split())
def unit(value):return str(value).lower() if value else None
def code(name):return re.sub('[^A-Z0-9]+','_',name.upper()).strip('_')[:80]
OLD={'code':'CABAI_MERAH','canonical_name':'Cabai Merah','category_code':'SAYUR','base_unit':'kg','aliases':['Cabai Merah','Cabe Merah'],'metadata':{'retained':'evidence'},'active':True}

class PlanTests(unittest.TestCase):
    def test_saved_dried_master_beats_the_generic_fresh_chili_mapping(self):
        path=Path(__file__).resolve().parents[1]/'backend/inventory_api.py'
        tree=ast.parse(path.read_text())
        wanted={'classify_item','_classify_item','_candidate_contains','RequestItemMatchers'}
        nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in wanted]
        ns={'re':re,'Any':Any,'deepcopy':deepcopy,'normalize_name':norm,'stock_type':lambda value:{'method':'ITEM_TYPE_RULE','code':'CABAI_MERAH'}}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)
        masters=[{'code':'CABAI_MERAH','canonical_name':'Cabai Merah','normalized_canonical_name':'cabai merah','aliases':['cabe merah'],'priority':100},
                 {'code':'CABAI_MERAH_KERING','canonical_name':'Cabai Merah Kering','normalized_canonical_name':'cabai merah kering','aliases':['cabe merah kering'],'priority':100}]
        self.assertEqual(ns['classify_item']('Cabai Merah Kering',masters)['inventoryItemCode'],'CABAI_MERAH_KERING')
        self.assertEqual(ns['classify_item']('Cabe Merah Kering',masters)['inventoryItemCode'],'CABAI_MERAH_KERING')
        self.assertEqual(ns['classify_item']('Cabai Merah',masters)['inventoryItemCode'],'CABAI_MERAH')

    def test_dried_chili_has_its_own_master_not_a_fresh_chili_alias(self):
        plan=build_master_plan({'code':'CABAI_MERAH_KERING','canonical_name':'Cabai Merah Kering','base_unit':'kg','require_unit':True},None,norm,unit,code)
        self.assertEqual(plan['proposed']['code'],'CABAI_MERAH_KERING')
        self.assertEqual(plan['proposed']['aliases'],['Cabai Merah Kering'])
        self.assertEqual(plan['expectedBeforeHash'],snapshot_hash(None))
        self.assertTrue(plan['canCommit'])
        for alias in ['Cabai Merah','Cabe Merah','cabai']:
            with self.subTest(alias=alias),self.assertRaises(ValueError):
                build_master_plan({'canonical_name':'Cabai Merah Kering','base_unit':'kg','aliases':[alias]},None,norm,unit,code)

    def test_alias_only_preserves_unit_category_metadata_name_and_old_aliases(self):
        old=deepcopy(OLD)
        plan=build_master_plan({'code':'CABAI_MERAH','aliases':['Cabe merah segar']},old,norm,unit,code)
        for key in ['canonical_name','base_unit','category_code','metadata','active']:
            self.assertEqual(plan['proposed'][key],old[key])
        self.assertTrue(set(old['aliases'])<=set(plan['proposed']['aliases']))
        self.assertEqual(plan['changedFields'],['aliases'])
        self.assertEqual(old,OLD)

    def test_repeated_alias_is_noop_and_unit_required_for_controlled_new_master(self):
        self.assertFalse(build_master_plan({'code':'CABAI_MERAH','aliases':['Cabai Merah']},OLD,norm,unit,code)['canCommit'])
        with self.assertRaises(ValueError):build_master_plan({'canonical_name':'Cabai Kering','require_unit':True},None,norm,unit,code)

    def test_metadata_patch_preserves_unmentioned_keys_and_activation_is_explicit(self):
        old={**OLD,'active':False}
        plan=build_master_plan({'metadata':{'new':'rule'},'aliases':['Cabe']},old,norm,unit,code)
        self.assertFalse(plan['proposed']['active'])
        self.assertEqual(plan['proposed']['metadata'],{'retained':'evidence','new':'rule'})
        active=build_master_plan({'active':True},old,norm,unit,code)
        self.assertTrue(active['proposed']['active'])

class HTTPError(Exception):
    def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail

class DB:
    def __init__(self,before=None,conflicts=None,late_conflict=False):
        self.before=before;self.conflicts=conflicts or {};self.late_conflict=late_conflict
        self.calls=[];self.one=None;self.commits=0
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return self
    def execute(self,sql,params=None):
        sql=' '.join(sql.lower().split());self.calls.append((sql,params));self.one=None
        if sql.startswith('select m.code'):self.one=deepcopy(self.before)
        elif sql.startswith('select inventory_item_code'):
            owner=self.conflicts.get(params[0]);self.one={'inventory_item_code':owner} if owner and owner!=params[1] else None
        elif sql.startswith('insert into inventory_item_aliases'):
            self.one=None if self.late_conflict else {'id':1}
    def fetchone(self):return self.one
    def commit(self):self.commits+=1

def endpoint(db):
    path=Path(__file__).resolve().parents[1]/'backend/inventory_api.py'
    fn=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='upsert_inventory_item')
    fn.decorator_list=[]
    ns={'InventoryMasterItemIn':object,'Any':Any,'require_db':lambda:None,'connection':lambda:db,'default_item_code':code,'canonical_unit':unit,'normalize_name':norm,'HTTPException':HTTPError,'json':json}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),ns)
    return ns['upsert_inventory_item']

def payload(**fields):
    values={'code':None,'canonical_name':None,'commit':False,'require_unit':False,'require_unchanged':False,'expected_before_hash':None,**fields}
    return SimpleNamespace(**values,model_dump=lambda **kwargs:fields)

class EndpointTests(unittest.TestCase):
    def test_preview_does_not_insert_master_or_alias_even_with_valid_fields(self):
        db=DB();out=endpoint(db)(payload(code='CABAI_MERAH_KERING',canonical_name='Cabai Merah Kering',base_unit='kg',require_unit=True))
        self.assertTrue(out['canCommit']);self.assertFalse(out['committed'])
        self.assertEqual(db.commits,0)
        self.assertFalse(any(sql.startswith(('insert','update','delete')) for sql,_ in db.calls))

    def test_alias_conflict_is_rejected_during_preview(self):
        db=DB(conflicts={'lada hitam':'LADA_HITAM'})
        with self.assertRaises(HTTPError) as e:
            endpoint(db)(payload(code='LADA_PUTIH',canonical_name='Lada Putih',base_unit='kg',aliases=['Lada Hitam']))
        self.assertEqual(e.exception.status_code,409);self.assertEqual(db.commits,0)

    def test_stale_master_snapshot_never_mutates(self):
        db=DB(before=OLD)
        with self.assertRaises(HTTPError) as e:
            endpoint(db)(payload(code='CABAI_MERAH',aliases=['Cabe Segar'],commit=True,require_unchanged=True,expected_before_hash=snapshot_hash(None)))
        self.assertEqual(e.exception.status_code,409)
        self.assertFalse(any(sql.startswith(('insert','update','delete')) for sql,_ in db.calls))

    def test_approved_addition_preserves_fields_and_never_touches_stock(self):
        db=DB(before=OLD)
        out=endpoint(db)(payload(code='CABAI_MERAH',aliases=['Cabe Segar'],commit=True,require_unchanged=True,expected_before_hash=snapshot_hash(OLD)))
        self.assertTrue(out['committed']);self.assertFalse(out['stockMutation'])
        self.assertEqual(out['proposed']['category_code'],'SAYUR')
        self.assertEqual(db.commits,1)
        self.assertFalse(any('stock_opname' in sql or 'inventory_movements' in sql for sql,_ in db.calls))

    def test_alias_owner_race_cannot_reassign_an_alias(self):
        db=DB(before=OLD,late_conflict=True)
        with self.assertRaises(HTTPError) as e:
            endpoint(db)(payload(code='CABAI_MERAH',aliases=['Cabe Segar'],commit=True,require_unchanged=True,expected_before_hash=snapshot_hash(OLD)))
        self.assertEqual(e.exception.status_code,409);self.assertEqual(db.commits,0)
        sql=next(sql for sql,_ in db.calls if sql.startswith('insert into inventory_item_aliases'))
        self.assertIn('where inventory_item_aliases.inventory_item_code=excluded.inventory_item_code',sql)

if __name__=='__main__':unittest.main()
