import unittest
from copy import deepcopy
from unittest.mock import patch
from types import ModuleType
import test_generated_document_api as fixture  # isolated API/DB fixtures, no live services
from backend.generated_document_logic import merge_final_documents
from backend.lpdh_logic import parameters
from backend.generated_document_maker import export_snapshot, maker_category
from fastapi import HTTPException


def document():
    return dict(id=9,site='MAJA',serviceDate='2026-10-06',status='FINAL',documentType='INSENTIF_MITRA',
        documentNumber='003/INS-MITRA/DMM/X/2026',total=5572000,driveUri='https://drive.google.com/file/d/synthetic/view',
        header={'documentProfileKey':'YAYASAN'},items=[dict(itemName='Insentif Mitra',category='Insentif Mitra',quantity=1,unit='hari',unitPrice=5572000,lineTotal=5572000,metadata={})])


class Cursor:
    def __init__(self): self.calls=[]; self.result=None; self.export=None
    def execute(self,sql,args=()):
        self.calls.append((sql,args))
        if sql.startswith('select accountant_invoice_id'): self.result=self.export
        elif sql.startswith('select id from accountant_invoices'): self.result=None
        elif 'insert into accountant_invoices(' in sql: self.result={'id':100}
        elif sql.startswith('insert into generated_document_maker_exports'):
            self.export={'accountant_invoice_id':args[1],'maker_id':args[2]}
        elif sql.startswith('update generated_document_maker_exports'):
            self.export['maker_id']=args[0]
    def fetchone(self): return self.result


class MitraMakerTests(unittest.TestCase):
    def test_existing_manual_invoice_does_not_create_duplicate(self):
        class ConflictCursor(Cursor):
            def execute(self,sql,args=()):
                super().execute(sql,args)
                if sql.startswith('select id from accountant_invoices'): self.result={'id':177}
        cur=ConflictCursor()
        with self.assertRaises(HTTPException) as caught: export_snapshot(cur,document(),'OWNER')
        self.assertEqual(caught.exception.status_code,409)
        self.assertFalse(any(sql.startswith('insert') for sql,args in cur.calls))
    def test_categories_follow_accountant_contract(self):
        for kind,expected in [('BAHAN_BAKU','BAHAN_BAKU'),('OPERASIONAL','OPERASIONAL_LAIN'),('INSENTIF_MITRA','SEWA_MITRA'),('UPAH_RELAWAN','GAJI_RELAWAN'),('INSENTIF_GURU_KADER','UPAH')]:
            self.assertEqual(maker_category({**document(),'documentType':kind}),expected)
        self.assertEqual(maker_category({**document(),'documentType':'UPAH_RELAWAN','header':{'combinedPayments':True}}),'UPAH')
    def test_pdf_excel_and_model(self):
        from io import BytesIO
        from pypdf import PdfReader
        from openpyxl import load_workbook
        from backend.generated_document_pdf import render_document_pdf
        from backend.generated_document_excel import render_document_excel
        doc=document();doc['header'].update(issuerName='Yayasan Uji',recipientName='SPPG Uji',recipientAddress='Alamat Uji',senderSignatory='Pengirim')
        text=' '.join(p.extract_text() for p in PdfReader(BytesIO(render_document_pdf(doc))).pages)
        text=' '.join(text.split())
        self.assertIn('INVOICE INSENTIF MITRA / YAYASAN',text)
        self.assertIn(doc['documentNumber'],text)
        wb=load_workbook(BytesIO(render_document_excel(doc)))
        values=[cell.value for row in wb.active for cell in row]
        self.assertIn('INVOICE INSENTIF MITRA / YAYASAN',values)
        payload=dict(site='MAJA',document_type='INSENTIF_MITRA',service_date='2026-10-06',document_number=doc['documentNumber'],header_payload=doc['header'],items=[dict(item_name='Insentif Mitra',quantity=1,unit='hari',unit_price=5572000)])
        self.assertEqual(fixture.api.GeneratedDocumentIn(**payload).document_type,'INSENTIF_MITRA')
        with self.assertRaises(ValueError):fixture.api.GeneratedDocumentIn(**{**payload,'header_payload':{**doc['header'],'documentProfileKey':'KOPERASI'}})

    def test_mitra_evidence_does_not_enter_operations_and_cancel_restores(self):
        base={'incentive':{'paidAmount':5572000,'receiptNo':'KW-OLD','evidenceLink':'https://old.example'},'operations':[]}
        result=merge_final_documents(base,[document()])
        self.assertEqual(result['operations'],[])
        self.assertEqual(result['incentive']['paidAmount'],5572000)
        self.assertEqual(result['incentive']['evidenceLink'],document()['driveUri'])
        self.assertEqual(result['incentive']['receiptNo'],document()['documentNumber'])
        restored=merge_final_documents(result,[])
        self.assertEqual(restored['incentive']['receiptNo'],'KW-OLD')
        self.assertEqual(restored['incentive']['evidenceLink'],'https://old.example')
        later=deepcopy(result); later['incentive']['evidenceLink']='https://manual.example'
        self.assertEqual(merge_final_documents(later,[])['incentive']['evidenceLink'],'https://manual.example')
        with self.assertRaises(ValueError): merge_final_documents(base,[document(),{**document(),'id':10}])

    def test_no_index_policy(self):
        p=parameters({'parameters':{'noIndexCompensation':True,'cityIndex':9,'applyIndexOp':True,'applyIndexRaw':True,'operationalPerPm':2786}})
        self.assertEqual(p['operationalPerPm'],3000)
        self.assertFalse(p['applyIndexOp']); self.assertFalse(p['applyIndexRaw']); self.assertEqual(p['cityIndex'],1)

    def test_one_maker_cover_total_and_retry(self):
        maker_module=ModuleType('backend.accountant_document_api')
        maker_module._create_maker=lambda cur,invoice,site,amount,reference: {'makerId':200}
        cur=Cursor(); doc=document(); doc['documentType']='UPAH_RELAWAN'; doc['header']={'combinedPayments':True}; doc['total']=6962000
        with patch.dict('sys.modules',{'backend.accountant_document_api':maker_module}):
            first=export_snapshot(cur,doc,'OWNER'); second=export_snapshot(cur,doc,'OWNER')
        self.assertEqual(first['maker_id'],200); self.assertTrue(second['duplicate'])
        inserts=[args for sql,args in cur.calls if 'insert into accountant_invoices(' in sql]
        self.assertEqual(len(inserts),1); self.assertEqual(inserts[0][7],6962000)
        cur.export['maker_id']=None
        with patch.dict('sys.modules',{'backend.accountant_document_api':maker_module}):
            replacement=export_snapshot(cur,doc,'OWNER')
        self.assertEqual(replacement['accountant_invoice_id'],100)
        self.assertEqual(replacement['maker_id'],200)
        self.assertEqual(len([sql for sql,args in cur.calls if 'insert into accountant_invoices(' in sql]),1)
        cur.export={'accountant_invoice_id':None,'maker_id':None}
        with patch.dict('sys.modules',{'backend.accountant_document_api':maker_module}):
            recreated=export_snapshot(cur,doc,'OWNER')
        self.assertEqual(recreated['maker_id'],200)
        self.assertEqual(len([sql for sql,args in cur.calls if 'insert into accountant_invoices(' in sql]),2)
        self.assertFalse(any('PAID' in sql or 'APPROVED' in sql for sql,args in cur.calls))
        for status in ['DRAFT','CANCELLED']:
            with self.assertRaises(HTTPException): export_snapshot(Cursor(),{**doc,'status':status},'OWNER')
        with self.assertRaises(HTTPException): export_snapshot(Cursor(),{**doc,'driveUri':''},'OWNER')
