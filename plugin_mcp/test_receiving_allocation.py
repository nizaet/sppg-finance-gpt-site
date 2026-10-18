"""Regression tests for pure PO allocation functions, without DB/auth imports."""
import ast
from collections import defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest

source=Path(__file__).resolve().parents[1]/'backend/receiving_multi_po_runtime_patch.py'
tree=ast.parse(source.read_text())
functions={'_same_family','_order','_resolve_line','_resolve_report','_score'}
unit=ast.Module(body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in functions],type_ignores=[])
op=SimpleNamespace(normalize_text=lambda value:value.lower(),canonical_unit=lambda value:value.lower(),name_similarity=lambda name,item:(0,'none'))
ns={'op':op,'date':date,'Any':Any,'defaultdict':defaultdict,'_MIN_SCORE':.62,'_AMBIGUITY_MARGIN':.035}
exec(compile(unit,str(source),'exec'),ns)

def item(po,index,name,qty,day=19):
    return {'purchase_order_id':po,'id':index,'item_name':name,'po_qty':qty,'received_total':0,'unit':'kg','distribution_date':date(2026,10,day),'po_status':'SENT'}

class ReportAllocationTests(unittest.TestCase):
    def test_holil_full_delivery_does_not_spill_tiny_onion_excess_into_next_day(self):
        names=['Jagung Manis','Labu Siam','Gula Merah','Wijen','Bawang Merah','Bawang Putih','Melon']
        actual=[55.68,63.72,5.04,1,4.06,3.06,212.12]
        planned=[55,60,5,1,4,3,210]
        rows=[{'reported_item_name':n,'received_qty':q,'unit':'kg'} for n,q in zip(names,actual)]
        items=[item(433,i,n,q) for i,(n,q) in enumerate(zip(names,planned),1794)]
        items += [item(439,1833,'Bawang Merah',5,20),item(439,1834,'Bawang Putih',6,20)]
        result,policy=ns['_resolve_report'](rows,items,date(2026,10,18))
        allocations=[a for row in result for a in row['allocations']]
        self.assertEqual({a['purchase_order_id'] for a in allocations},{433})
        self.assertAlmostEqual(sum(a['allocated_qty'] for a in allocations),344.68)
        self.assertAlmostEqual(result[4]['variance_qty'],.06)
        self.assertAlmostEqual(result[5]['variance_qty'],.06)
        self.assertEqual(result[4]['po_qty'],4)
        self.assertEqual(policy['mode'],'SINGLE_PO_REPORT')

    def test_genuine_disjoint_po_items_still_match_multiple_orders(self):
        rows=[{'reported_item_name':'Jagung','received_qty':20,'unit':'kg'},{'reported_item_name':'Melon','received_qty':30,'unit':'kg'}]
        result,policy=ns['_resolve_report'](rows,[item(433,1,'Jagung',20),item(439,2,'Melon',30,20)],date(2026,10,18))
        self.assertEqual({a['purchase_order_id'] for row in result for a in row['allocations']},{433,439})
        self.assertEqual(policy['mode'],'MULTI_PO_ITEMS')

    def test_explicit_po_scope_and_actual_overweight_are_preserved(self):
        row={'reported_item_name':'Ayam Fillet','received_qty':407.52,'unit':'kg'}
        result,_=ns['_resolve_report']([row],[item(441,1,'Ayam Fillet',407)],date(2026,10,17))
        self.assertEqual(result[0]['po_qty'],407)
        self.assertAlmostEqual(result[0]['variance_qty'],.52)
        self.assertAlmostEqual(sum(a['allocated_qty'] for a in result[0]['allocations']),407.52)
