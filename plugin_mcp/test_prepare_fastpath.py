import asyncio
import unittest
from unittest.mock import AsyncMock,MagicMock,patch
from plugin_mcp.approval_workflow import prepare_change

class PrepareFastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_and_knowledge_run_in_parallel_once_and_keep_gate(self):
        preview_entered=asyncio.Event();knowledge_entered=asyncio.Event()
        async def preview(change):
            preview_entered.set()
            await knowledge_entered.wait()
            return {'canCommit':True,'reportedItems':[]},None,{}
        async def knowledge(*args,**kwargs):
            knowledge_entered.set()
            await preview_entered.wait()
            return {'databaseReady':True,'canonicalKnowledge':{'version':'v6'},'liveContext':{}}
        with patch('plugin_mcp.approval_workflow._preview',new_callable=AsyncMock,side_effect=preview) as p,patch('plugin_mcp.approval_workflow.core_request',new_callable=AsyncMock,side_effect=knowledge) as k,patch('plugin_mcp.approval_workflow._db_ready'),patch('plugin_mcp.approval_workflow._ensure_table'),patch('plugin_mcp.approval_workflow.connection',return_value=MagicMock()),patch('plugin_mcp.approval_workflow.operational_writes_enabled',return_value=True):
            result=await asyncio.wait_for(prepare_change('RECORD_GOODS_RECEIPT',{'text':'Ayam Fillet - 407,52 kg','received_date':'2026-10-17'},'CEMPLANG','Performance preview only'),timeout=1)
        self.assertEqual(result['status'],'PENDING')
        self.assertTrue(result['runtimeKnowledge']['loaded'])
        self.assertIn('approvalId',result)
        self.assertNotIn('committed',result)
        self.assertEqual(p.await_count,1);self.assertEqual(k.await_count,1)
        self.assertEqual(p.call_args.args[0].payload['received_at'],'2026-10-17T00:00:00+07:00')

    async def test_invalid_actual_quantity_stays_draft_without_core_receipt_call(self):
        with patch('plugin_mcp.approval_workflow._preview',new_callable=AsyncMock) as p,patch('plugin_mcp.approval_workflow.core_request',new_callable=AsyncMock,return_value={'databaseReady':True}),patch('plugin_mcp.approval_workflow._db_ready'),patch('plugin_mcp.approval_workflow._ensure_table'),patch('plugin_mcp.approval_workflow.connection',return_value=MagicMock()):
            result=await prepare_change('RECORD_GOODS_RECEIPT',{'items':[{'item_name':'Ayam','received_qty':-1,'unit':'kg'}]},'CEMPLANG','Invalid data must not be submitted')
        self.assertEqual(result['status'],'DRAFT');self.assertFalse(result['preview']['canCommit'])
        p.assert_not_awaited()

if __name__=='__main__':unittest.main()
