import unittest
from unittest.mock import AsyncMock, patch
from plugin_mcp.approval_workflow import ChangeRequest, _preview, _execute, CONTROL_ACTIONS
from plugin_mcp.form_fields import apply_form

class SubstitutionTests(unittest.IsolatedAsyncioTestCase):
    def change(self, **payload):
        return ChangeRequest(action='RECORD_RECEIPT_SUBSTITUTION', site='MAJA', reason='Buncis tidak tersedia', payload={'purchase_order_id':12,'purchase_order_item_id':33,'replacement_item_code':'KACANG_PANJANG','replaces_qty':40,'received_qty':35,'vendor_cost_price':12000,'expected_fulfilled_qty':10,'received_at':'2026-10-24T08:00:00+07:00','request_id':'fixed-id','reason':'Buncis tidak tersedia', **payload})
    async def test_preview_never_writes_and_preserves_distinct_quantities(self):
        call=AsyncMock(return_value={'canCommit':True})
        with patch('plugin_mcp.approval_workflow.core_request',call):
            await _preview(self.change(commit=True))
        self.assertIn('RECORD_RECEIPT_SUBSTITUTION',CONTROL_ACTIONS)
        body=call.call_args.kwargs['json_body']
        self.assertFalse(body['commit']); self.assertEqual(body['replaces_qty'],40); self.assertEqual(body['received_qty'],35)
        self.assertEqual(call.call_args.args[1],'/v1/purchase-orders/12/receiving-substitution')
    async def test_execution_uses_same_id_and_gate_constructs_commit(self):
        call=AsyncMock(return_value={'committed':True,'receiptId':5})
        with patch('plugin_mcp.approval_workflow.core_request',call):
            await _execute(self.change(commit=False))
        body=call.call_args.kwargs['json_body']
        self.assertTrue(body['commit']); self.assertEqual(body['request_id'],'fixed-id')
    async def test_cross_site_blocked(self):
        with self.assertRaises(ValueError): await _preview(self.change(site='CEMPLANG'))
    def test_edit_quantity_does_not_change_original_closure(self):
        data=apply_form('RECORD_RECEIPT_SUBSTITUTION',self.change().payload,{}, {'fields':{'received_qty':'32,5'}})
        self.assertEqual(data['received_qty'],32.5);self.assertEqual(data['replaces_qty'],40)
