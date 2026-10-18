"""Regress the actual 22-papan repeat report without production writes."""
import ast
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import MagicMock,Mock
from zoneinfo import ZoneInfo
from backend.receipt_identity import jakarta_day_bounds,receipt_signature


class ReceiptIdentityTests(unittest.TestCase):
    def test_receipt_495_midnight_jakarta_belongs_to_october_18(self):
        start,end=jakarta_day_bounds(date(2026,10,18))
        received=datetime.fromisoformat('2026-10-17T17:00:00+00:00')
        self.assertTrue(start<=received<end)
        self.assertEqual(start.astimezone(timezone.utc),received)
        previous_start,previous_end=jakarta_day_bounds(date(2026,10,17))
        self.assertFalse(previous_start<=received<previous_end)
        self.assertEqual((end-start).total_seconds(),86400)

    def test_split_overweight_rows_equal_report_total_without_float_drift(self):
        sig=lambda rows:receipt_signature(rows,str.lower,str.lower)
        self.assertEqual(sig([{'item_name':'Bawang Merah','received_qty':'4.06','unit':'kg'}]),sig([{'reported_item_name':'Bawang Merah','received_qty':'4','unit':'kg'},{'reported_item_name':'Bawang Merah','received_qty':'.06','unit':'kg'}]))
        self.assertNotEqual(sig([{'item_name':'Tahu Putih','received_qty':3168,'unit':'pcs'}]),sig([{'item_name':'Tahu Putih','received_qty':22,'unit':'papan'}]))
        for qty in ['NaN','Infinity',-1,None]:
            self.assertIsNone(sig([{'item_name':'Tahu','received_qty':qty,'unit':'pcs'}]))


class DuplicateFlowTests(unittest.TestCase):
    def setUp(self):
        self.reported=[{'reported_item_name':'Tahu Putih','received_qty':3168,'unit':'pcs','original_received_qty':22,'original_unit':'papan'}]
        self.record={'receipt_id':495,'purchase_order_id':430,'received_at':datetime.fromisoformat('2026-10-17T17:00:00+00:00'),'source_external_id':None,'po_code':'PO-CEMPLANG-20261019-HAJI_BADRI','vendor_code':'HAJI_BADRI','po_status':'RECEIVED','receipt_items':self.reported}
        self.cur=MagicMock();self.cur.fetchall.return_value=[self.record]
        conn=MagicMock();conn.__enter__.return_value=conn;conn.cursor.return_value.__enter__.return_value=self.cur
        op=SimpleNamespace(WhatsAppReceiptIn=object,require_db=Mock(),normalize_site=str.upper,extract_receipt_items=lambda text:self.reported,infer_vendor=lambda text:'HAJI_BADRI',normalize_text=str.lower,canonical_unit=str.lower,connection=lambda:conn)
        class HTTPError(Exception):
            def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail
        self.ns={'op':op,'Any':Any,'date':date,'datetime':datetime,'ZoneInfo':ZoneInfo,'jakarta_day_bounds':jakarta_day_bounds,'receipt_signature':receipt_signature,'HTTPException':HTTPError,'_preferred_vendor':lambda rows:None,'_candidate_pos':Mock(side_effect=AssertionError('Closed PO must be recognised through receiving first'))}
        path=Path(__file__).resolve().parents[1]/'backend/receiving_multi_po_runtime_patch.py'
        functions={'_target_date','_existing_receipts','_existing_preview','receive_from_whatsapp_v2'}
        module=ast.Module(body=[n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in functions],type_ignores=[])
        exec(compile(module,str(path),'exec'),self.ns)
        self.payload=SimpleNamespace(site='CEMPLANG',text='datang tahu 22 papan dari badri cemplang',vendor_code=None,purchase_order_id=None,received_at=datetime(2026,10,18,tzinfo=ZoneInfo('Asia/Jakarta')),commit=False)

    def test_original_short_report_finds_completed_po_and_existing_receipt(self):
        result=self.ns['receive_from_whatsapp_v2'](self.payload)
        self.assertEqual(result['receiptState'],'POSSIBLE_DUPLICATE')
        self.assertEqual(result['existingReceiptId'],495)
        self.assertEqual(result['purchaseOrderId'],430)
        self.assertFalse(result['canCommit']);self.assertFalse(result['committed'])
        self.assertFalse(result['requiresConfirmation'])
        self.ns['_candidate_pos'].assert_not_called()
        sql,params=self.cur.execute.call_args.args
        self.assertNotIn('upper(po.status)=any',sql)
        self.assertIn('upper(po.site)=upper(%s)',sql)
        self.assertEqual(params[-1],'HAJI_BADRI')
        self.assertEqual(self.cur.execute.call_count,1)

    def test_duplicate_commit_is_blocked_before_stock_or_receipt_writes(self):
        self.payload.commit=True
        with self.assertRaises(self.ns['HTTPException']) as caught:
            self.ns['receive_from_whatsapp_v2'](self.payload)
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(self.cur.execute.call_count,1)
        self.assertTrue(self.cur.execute.call_args.args[0].startswith('select'))

    def test_different_quantity_is_not_marked_as_the_same_receipt(self):
        self.reported=[{'reported_item_name':'Tahu Putih','received_qty':144,'unit':'pcs'}]
        result=self.ns['_existing_receipts'](self.cur,self.payload,self.reported,'HAJI_BADRI')
        self.assertEqual(result,[])
