import unittest
from copy import deepcopy
import test_generated_document_api
from fastapi import HTTPException
from backend.topup_receipt import protect_final_rows

class Cursor:
    def execute(self,*args):pass
    def fetchall(self):return [dict(id=7,document_number='002/KWT/X/2026',pdf_link='https://drive.google.com/test',snapshot={'funds':dict(date='2026-10-07',rawAmount=260365618,operationalAmount=77721080,incentiveAmount=50518702,reference='00213')})]

class FinalGuardTests(unittest.TestCase):
    def data(self):
        return {'balance':{'openingRaw':0},'topups':[dict(date='2026-10-07',rawAmount=260365618,operationalAmount=77721080,incentiveAmount=50518702,reference='',_topupReceiptId='7',receiptNo='002/KWT/X/2026',evidenceLink='https://drive.google.com/test')]}
    def test_balance_edit_and_reference_annotation(self):
        d=self.data();d['balance']['openingRaw']=1000
        protect_final_rows(Cursor(),'CEMPLANG','2026-10-07',d)
        self.assertEqual(d['topups'][0]['_topupReceiptId'],7)
        self.assertEqual(d['balance']['openingRaw'],1000)
    def test_missing_identity_recovered_from_unique_proof(self):
        d=self.data();d['topups'][0].pop('_topupReceiptId')
        protect_final_rows(Cursor(),'CEMPLANG','2026-10-07',d)
        self.assertEqual(d['topups'][0]['_topupReceiptId'],7)
    def test_mutation_deletion_and_duplicate_blocked(self):
        for key,value in [('rawAmount',1),('date','2026-10-08')]:
            d=self.data();d['topups'][0][key]=value
            with self.assertRaises(HTTPException):protect_final_rows(Cursor(),'CEMPLANG','2026-10-07',d)
        for rows in [[],self.data()['topups']*2]:
            with self.assertRaises(HTTPException):protect_final_rows(Cursor(),'CEMPLANG','2026-10-07',{'topups':rows})

if __name__=='__main__':unittest.main()

