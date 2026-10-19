import json,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,MagicMock,patch
from plugin_mcp.approval_workflow import ChangeRequest,_preview,_execute,prepare_change,confirm_change,_hash_json
from plugin_mcp.v0186_tools import previewOrSaveSppgInventoryItemMaster
from plugin_mcp.test_approval_workflow import TicketConnection

ACTION='UPSERT_INVENTORY_ITEM_MASTER'
FIELDS={'code':'CABAI_MERAH_KERING','canonical_name':'Cabai Merah Kering','base_unit':'kg','aliases':['Cabe Merah Kering']}
PLAN={'committed':False,'canCommit':True,'expectedBeforeHash':'reviewed-hash','before':None,'proposed':FIELDS,'scope':'GLOBAL_SHARED_MAJA_CEMPLANG'}

class MasterWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_master_tool_only_prepares_even_if_commit_true_is_supplied(self):
        with patch('plugin_mcp.approval_workflow.prepare_change',new_callable=AsyncMock,return_value={'status':'PENDING'}) as prepare:
            result=await previewOrSaveSppgInventoryItemMaster({**FIELDS,'commit':True})
        self.assertEqual(result['status'],'PENDING')
        self.assertEqual(prepare.call_args.args[0],ACTION)
        self.assertEqual(prepare.call_args.args[2],'GLOBAL')
        self.assertFalse(prepare.call_args.args[1]['commit'])

    async def test_preview_is_readonly_and_reports_shared_master_without_stock_effect(self):
        change=ChangeRequest(action=ACTION,payload={**FIELDS,'commit':True},site='GLOBAL',reason='Master preview regression')
        with patch('plugin_mcp.approval_workflow.core_request',new_callable=AsyncMock,return_value=PLAN) as request:
            result,before,impact=await _preview(change)
        self.assertFalse(request.call_args.kwargs['json_body']['commit'])
        self.assertTrue(request.call_args.kwargs['json_body']['require_unit'])
        self.assertEqual(impact['stock'],'NONE');self.assertEqual(impact['finance'],'NONE')
        self.assertEqual(impact['master'],'GLOBAL_SHARED_MAJA_CEMPLANG')

    async def test_prepare_persists_server_snapshot_for_atomic_confirmation(self):
        conn=MagicMock()
        with patch('plugin_mcp.approval_workflow._preview',new_callable=AsyncMock,return_value=(PLAN,None,{'stock':'NONE'})),patch('plugin_mcp.approval_workflow.core_request',new_callable=AsyncMock,return_value={'databaseReady':True}),patch('plugin_mcp.approval_workflow._db_ready'),patch('plugin_mcp.approval_workflow._ensure_table'),patch('plugin_mcp.approval_workflow.connection',return_value=conn):
            result=await prepare_change(ACTION,{**FIELDS,'expected_before_hash':'user-supplied-hash'},'GLOBAL','Prepare shared master')
        self.assertEqual(result['status'],'PENDING')
        params=conn.__enter__.return_value.cursor.return_value.__enter__.return_value.execute.call_args.args[1]
        persisted=json.loads(params[5])
        self.assertEqual(persisted['expected_before_hash'],'reviewed-hash')
        self.assertTrue(persisted['require_unchanged'])

    async def test_execute_requires_review_hash_and_enforces_it_at_core(self):
        change=ChangeRequest(action=ACTION,payload=FIELDS,site='GLOBAL',reason='Master gate regression')
        with patch('plugin_mcp.approval_workflow.core_request',new_callable=AsyncMock) as request:
            with self.assertRaises(ValueError):await _execute(change)
            request.assert_not_awaited()
        change.payload={**FIELDS,'expected_before_hash':'reviewed-hash','require_unchanged':False}
        with patch('plugin_mcp.approval_workflow.core_request',new_callable=AsyncMock,return_value={'committed':True}) as request:
            await _execute(change)
        body=request.call_args.kwargs['json_body']
        self.assertTrue(body['commit']);self.assertTrue(body['require_unchanged'])
        self.assertEqual(request.call_args.args[:2],('POST','/v1/inventory/items'))

    async def test_global_scope_cannot_expand_to_stock_or_finance(self):
        for action in ['RECORD_STOCK_OPNAME','CREATE_ACCOUNTANT_TRANSACTIONS','CREATE_PO']:
            with self.subTest(action=action),self.assertRaises(ValueError):
                await prepare_change(action,{},'GLOBAL','Global must be master-only')

    async def test_stale_master_cannot_execute_after_a_different_edit(self):
        before={'code':'CABAI_MERAH','aliases':['Cabai Merah']}
        state={'id':'master-test','operator_sub':'SPPG_OWNER','site':'GLOBAL','action':ACTION,'reason':'Alias review',
               'status':'PENDING','proposed_payload':{**FIELDS,'expected_before_hash':'reviewed-hash'},'preview_data':PLAN,
               'before_hash':_hash_json(before),'expires_at':datetime.now(timezone.utc)+timedelta(minutes=5)}
        changed={**before,'aliases':['Cabai Merah','Added elsewhere']}
        with patch('plugin_mcp.approval_workflow._db_ready'),patch('plugin_mcp.approval_workflow._ensure_table'),patch('plugin_mcp.approval_workflow.connection',return_value=TicketConnection(state)),patch('plugin_mcp.approval_workflow.operational_writes_enabled',return_value=True),patch('plugin_mcp.approval_workflow._preview',new_callable=AsyncMock,return_value=(PLAN,changed,{})),patch('plugin_mcp.approval_workflow._execute',new_callable=AsyncMock) as execute:
            result=await confirm_change(state['id'],'CONFIRM')
        self.assertEqual(result['status'],'STALE');execute.assert_not_awaited()
