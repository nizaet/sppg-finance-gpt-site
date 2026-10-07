import unittest
import json
from backend.delivery_package import document_dates,ensure_package

class Cursor:
    def __init__(self): self.packages={};self.counters={};self.result=None
    def execute(self,sql,args=()):
        if sql.startswith('select * from lpdh_delivery_packages'): self.result=self.packages.get(args[0])
        elif sql.startswith('select settings from lpdh_delivery_packages'): self.result=None
        elif 'insert into lpdh_delivery_counters' in sql:
            self.counters[args]=self.counters.get(args,0)+1;self.result={'value':self.counters[args]}
        elif 'insert into lpdh_delivery_packages' in sql:
            self.result={'document_id':args[0],'numbers':json.loads(args[3])};self.packages[args[0]]=self.result
    def fetchone(self): return self.result

class DeliveryTests(unittest.TestCase):
    def test_dates_cross_month_and_year(self):
        self.assertEqual(document_dates('2026-01-01'),{'PO':'2025-12-30','SJ':'2025-12-31','CKL':'2025-12-31','KUI':'2026-01-02'})
    def test_idempotent_per_invoice_and_site(self):
        cur=Cursor();row={'id':1,'site':'MAJA','service_date':'2026-10-05','status':'FINAL','document_type':'BAHAN_BAKU'}
        first=ensure_package(cur,row)
        self.assertEqual(first,ensure_package(cur,row));self.assertEqual(first['numbers']['PO'],'PO/2026/X/001')
        self.assertEqual(ensure_package(cur,{**row,'id':2,'document_type':'OPERASIONAL'})['numbers']['KUI'],'002/KUI.Banper/OP/X/2026')
        self.assertEqual(ensure_package(cur,{**row,'id':3,'site':'CEMPLANG'})['numbers']['SJ'],'SJ/202610/001')
        for kind in ['UPAH_RELAWAN','INSENTIF_GURU_KADER','INSENTIF_MITRA']:
            self.assertIsNone(ensure_package(cur,{**row,'document_type':kind}))
        self.assertIsNone(ensure_package(cur,{**row,'status':'DRAFT'}))
