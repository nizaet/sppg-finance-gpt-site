import unittest
from plugin_mcp.form_fields import apply_form, describe_form

class FormTests(unittest.TestCase):
    def test_receipt_selection_preserves_evidence_and_weights(self):
        original={'text':'• Jeruk Medan - 186,88 kg\n• Wortel - 50,68 kg','purchase_order_id':434}
        preview={'reportedItems':[{'reported_item_name':'Jeruk Medan','received_qty':186.88,'unit':'kg'},{'reported_item_name':'Wortel','received_qty':50.68,'unit':'kg'}]}
        changed=apply_form('RECORD_GOODS_RECEIPT',original,preview,{'rows':[{'index':0,'fields':{'received_qty':'186,88'}}]})
        self.assertEqual(changed['text'],'Jeruk Medan - 186.88 kg')
        self.assertEqual(changed['source_raw_text'],original['text'])
        self.assertEqual(original['purchase_order_id'],434)
        self.assertIn('Wortel',original['text'])

    def test_row_ids_and_empty_selection_cannot_be_injected(self):
        payload={'items':[{'item_name':'Wortel','qty':1,'item_id':77}]}
        for rows in [[],[{'index':0,'fields':{'item_id':88}}],[{'index':0},{'index':0}]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                apply_form('CREATE_PO',payload,{}, {'rows':rows})

    def test_payment_edits_keep_debt_amount_and_date_consistent(self):
        payload={'items':[{'description':'Roti','amount':168000,'date':'2026-10-18','payment_status':'unpaid'}]}
        paid=apply_form('CREATE_ACCOUNTANT_TRANSACTIONS',payload,{}, {'rows':[{'index':0,'fields':{'payment_status':'paid'}}]})['items'][0]
        self.assertFalse(paid['is_debt']);self.assertEqual(paid['paid_amount'],168000);self.assertEqual(paid['paid_date'],'2026-10-18')
        unpaid=apply_form('CREATE_ACCOUNTANT_TRANSACTIONS',{'items':[paid]}, {}, {'rows':[{'index':0,'fields':{'payment_status':'unpaid'}}]})['items'][0]
        self.assertTrue(unpaid['is_debt']);self.assertEqual(unpaid['paid_amount'],0);self.assertIsNone(unpaid['paid_date'])
        with self.assertRaises(ValueError):
            apply_form('CREATE_ACCOUNTANT_TRANSACTIONS',payload,{}, {'rows':[{'index':0,'fields':{'payment_status':'partial','paid_amount':168000}}]})

    def test_date_picker_means_jakarta_not_server_timezone(self):
        changed=apply_form('RECORD_GOODS_RECEIPT',{}, {}, {'fields':{'received_at':'2026-10-18T02:35'}})
        self.assertEqual(changed['received_at'],'2026-10-18T02:35:00+07:00')
        shown=describe_form('RECORD_GOODS_RECEIPT',{'received_at':'2026-10-17T19:35:00Z'}, {})
        self.assertEqual(next(f['value'] for f in shown['fields'] if f['key']=='received_at'),'2026-10-18T02:35')

    def test_stock_checkbox_creates_reviewed_subset_with_original_master(self):
        payload={'text':'Wortel 5 kg, Timun 2 kg'}
        preview={'items':[{'clientKey':'0','itemName':'Wortel','canonicalItemName':'Wortel','inventoryItemCode':'S001','qty':5,'unit':'kg'},{'clientKey':'1','itemName':'Timun','qty':2,'unit':'kg'}]}
        result=apply_form('RECORD_STOCK_OPNAME',payload,preview,{'rows':[{'index':0,'fields':{'qty':4}}]})
        self.assertEqual(len(result['reviewed_items']),1)
        self.assertEqual(result['reviewed_items'][0]['qty'],4)
        self.assertEqual(result['reviewed_items'][0]['inventory_item_code'],'S001')
        self.assertEqual(result['text'],payload['text'])

if __name__=='__main__': unittest.main()
