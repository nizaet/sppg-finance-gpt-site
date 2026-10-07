"""Execute real cancellation handlers with an isolated database/Drive fixture."""
import ast
import unittest
from pathlib import Path
from unittest.mock import Mock
from typing import Any
from fastapi import HTTPException

ROOT=Path(__file__).resolve().parents[1]


class DB:
    def __init__(self, protected=False, linked=True):
        self.calls=[]; self.protected=protected; self.linked=linked; self.result=None
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def cursor(self): return self
    def commit(self): self.calls.append('COMMIT')
    def execute(self,sql,args=()):
        self.calls.append(sql)
        if 'select id,accountant_submission_id' in sql:
            self.result={'id':100,'accountant_submission_id':None,'invoice_number':'TEST','invoice_evidence_uri':'https://drive.google.com/source'}
        elif 'select document_id' in sql:
            self.result={'document_id':9} if self.linked else None
        elif 'select m.id,m.accountant_invoice_id' in sql:
            self.result={'id':200,'accountant_invoice_id':100,'status':'PAID' if self.protected else 'CREATED','has_receipt':self.protected,'approval_status':'APPROVED' if self.protected else 'PENDING'}
    def fetchone(self): return self.result
    def fetchall(self): return [{'id':200,'status':'PAID' if self.protected else 'CREATED','has_receipt':self.protected,'approval_status':'APPROVED' if self.protected else 'PENDING'}]


def handler(filename,name,db,drive):
    tree=ast.parse((ROOT/'backend'/filename).read_text(encoding='utf-8'))
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
    fn.decorator_list=[]
    namespace={'Any':Any,'HTTPException':HTTPException,'require_db':lambda:None,'connection':lambda:db,'_delete_drive_uri':drive}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),filename,'exec'),namespace)
    return namespace[name]


class MakerCancelTests(unittest.TestCase):
    def test_remove_flow_preserves_lpdh_drive_pdf(self):
        db=DB(); drive=Mock()
        result=handler('accountant_correction_api.py','delete_direct_accountant_invoice',db,drive)(100)
        self.assertTrue(result['deleted']); self.assertEqual(result['deletedMakerIds'],[200])
        self.assertEqual(result['driveCleanup']['reason'],'LPDH_FINAL_SOURCE_PRESERVED')
        drive.assert_not_called()
        self.assertTrue(any('delete from accountant_invoices' in sql for sql in db.calls))
        self.assertFalse(any('delete from generated_accountant_documents' in sql for sql in db.calls))

    def test_unrelated_manual_flow_keeps_existing_cleanup(self):
        db=DB(linked=False); drive=Mock(return_value={'deleted':True})
        handler('accountant_correction_api.py','delete_direct_accountant_invoice',db,drive)(100)
        drive.assert_called_once_with('https://drive.google.com/source')

    def test_pending_maker_cancel_keeps_invoice(self):
        db=DB(); drive=Mock()
        result=handler('accountant_status_api.py','cancel_bgn_maker',db,drive)(200)
        self.assertTrue(result['cancelled'])
        self.assertFalse(any('delete from accountant_invoices' in sql for sql in db.calls))

    def test_paid_data_protected_in_both_handlers(self):
        for file,name,value in [('accountant_correction_api.py','delete_direct_accountant_invoice',100),('accountant_status_api.py','cancel_bgn_maker',200)]:
            db=DB(protected=True); drive=Mock()
            with self.assertRaises(HTTPException) as caught: handler(file,name,db,drive)(value)
            self.assertEqual(caught.exception.status_code,409)
            self.assertFalse(any(sql.startswith('delete') for sql in db.calls))
            drive.assert_not_called()

    def test_provenance_foreign_keys_allow_reset_without_losing_source(self):
        sql=(ROOT/'schema/lpdh_maker_cancel_v047.sql').read_text()
        self.assertIn('on delete set null',sql)
        self.assertNotIn('delete from',sql.lower())
