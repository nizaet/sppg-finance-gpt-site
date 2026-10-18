import unittest
from plugin_mcp.form_fields import apply_form, describe_form

class FormTests(unittest.TestCase):
    def test_receipt_selection_preserves_evidence_and_weights(self):
        original={'text':'• Jeruk Medan - 186,88 kg\n• Wortel - 50,68 kg','purchase_order_id':434}
        preview={'reportedItems':[{'reported_item_name':'Jeruk Medan','received_qty':186.88,'unit':'kg'},{'reported_item_name':'Wortel','received_qty':50.68,'unit':'kg'}]}
        changed=apply_form('RECORD_GOODS_RECEIPT',original,preview,{'selected_indices':[0],'rows':[{'index':0,'fields':{'received_qty':'186,88'}}]})
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
        result=apply_form('RECORD_STOCK_OPNAME',payload,preview,{'selected_indices':[0],'rows':[{'index':0,'fields':{'qty':4}}]})
        self.assertEqual(len(result['reviewed_items']),1)
        self.assertEqual(result['reviewed_items'][0]['qty'],4)
        self.assertEqual(result['reviewed_items'][0]['inventory_item_code'],'S001')
        self.assertEqual(result['text'],payload['text'])

    def test_partial_edit_keeps_all_other_items_and_master_ids(self):
        original={'text':'original report'}
        names=['Jagung','Labu','Gula','Wijen','Bawang Merah','Bawang Putih','Melon']
        preview={'reportedItems':[{'reported_item_name':name,'received_qty':i+1,'unit':'kg'} for i,name in enumerate(names)]}
        changed=apply_form('RECORD_GOODS_RECEIPT',original,preview,{'rows':[{'index':4,'fields':{'received_qty':'4,06'}}]})
        self.assertEqual(len(changed['text'].splitlines()),7)
        self.assertIn('Melon - 7 kg',changed['text']);self.assertIn('Bawang Merah - 4.06 kg',changed['text'])
        self.assertEqual(changed['source_raw_text'],'original report')
        self.assertAlmostEqual(changed['receipt_input_summary']['actualQty'],27.06)
        self.assertEqual(changed['receipt_input_summary']['itemCount'],7)
        po={'items':[{'item_name':name,'qty':1,'item_id':i+77} for i,name in enumerate(names)]}
        updated=apply_form('CREATE_PO',po,{}, {'rows':[{'index':1,'fields':{'qty':2}}]})
        self.assertEqual(len(updated['items']),7);self.assertEqual(updated['items'][6]['item_id'],83)

    def test_nonfinite_values_and_invalid_selection_are_rejected(self):
        payload={'items':[{'item_name':'Wortel','qty':1,'item_id':77}]}
        for edits in [{'rows':[{'index':0,'fields':{'qty':'NaN'}}]}, {'rows':[{'index':0,'fields':{'qty':'Infinity'}}]}, {'selected_indices':[]},{'selected_indices':[True]},{'selected_indices':[0,0]},{'selected_indices':[1]}]:
            with self.subTest(edits=edits),self.assertRaises(ValueError): apply_form('CREATE_PO',payload,{},edits)

    def test_structured_receipt_edit_updates_canonical_text_as_well(self):
        payload={'text':'Jagung - 55 kg','items':[{'item_name':'Jagung','received_qty':55,'unit':'kg','item_id':7}]}
        updated=apply_form('RECORD_GOODS_RECEIPT',payload,{}, {'rows':[{'index':0,'fields':{'received_qty':55.68}}]})
        self.assertEqual(updated['text'],'Jagung - 55.68 kg')
        self.assertEqual(updated['items'][0]['item_id'],7)

if __name__=='__main__': unittest.main()
