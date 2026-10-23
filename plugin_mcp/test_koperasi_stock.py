"""Isolated SO tests; every commit test uses an in-memory fake connection."""
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from plugin_mcp.stock_opname_input import normalize_stock_input, stock_location, stock_core_payload, validate_change_scope


def sku_table():
    header = 'Tanggal: 23 Oktober 2026\n| SKU | Nama Barang | Sisa Stok Gudang | Satuan |\n| --- | --- | --- | --- |'
    rows = [f'| BRG-{i:03} | Barang Uji {i} @500 gr x 12 | {-i if i <= 18 else i} | kg |' for i in range(1, 106)]
    return header + '\n' + '\n'.join(rows)


class StockInputTests(unittest.TestCase):
    def test_105_skus_and_18_explicit_zero_corrections_preserve_source(self):
        text = sku_table()
        result = normalize_stock_input({'text': text, 'zero_negative_quantities': True})
        self.assertEqual(result['text'], text)
        self.assertEqual(len(result['reviewed_items']), 105)
        self.assertEqual(result['stock_input_summary']['zeroCorrectionCount'], 18)
        self.assertEqual([r['qty'] for r in result['reviewed_items'][:18]], [0] * 18)
        self.assertEqual(result['reviewed_items'][18]['qty'], 19)
        self.assertEqual(result['reviewed_items'][-1]['client_key'], 'BRG-105')
        self.assertIn('@500 gr x 12', result['reviewed_items'][0]['raw_item_name'])

    def test_negatives_are_never_silently_absorbed_or_made_positive(self):
        with self.assertRaisesRegex(ValueError, 'Negative physical stock'):
            normalize_stock_input({'text': sku_table()})

    def test_reviewed_operator_edits_and_selection_survive_repreparation(self):
        data = normalize_stock_input({'text': sku_table(), 'zero_negative_quantities': True})
        data['reviewed_items'][0]['qty'] = 2.5
        data['reviewed_items'] = data['reviewed_items'][:25]
        new = normalize_stock_input(data)
        self.assertEqual(len(new['reviewed_items']), 25)
        self.assertEqual(new['reviewed_items'][0]['qty'], 2.5)
        self.assertEqual(new['stock_input_summary']['rowCount'], 25)
        self.assertEqual(new['stock_input_summary']['zeroCorrectionCount'], 17)

    def test_sku_does_not_become_master_code_and_comma_qty_is_exact(self):
        text = '| SKU | Nama Barang | Sisa Stok Gudang | Satuan |\n| BRG-001 | Cuka @650ml x12 | 21,50 | btl |'
        row = normalize_stock_input({'text': text})['reviewed_items'][0]
        self.assertEqual(row['qty'], 21.5)
        self.assertEqual(row['unit'], 'botol')
        self.assertNotIn('inventory_item_code', row)
        self.assertEqual(row['client_key'], 'BRG-001')

    def test_duplicate_sku_or_missing_cells_fail_closed(self):
        header = '| SKU | Nama Barang | Sisa Stok Gudang | Satuan |\n'
        for rows in ['| A | B | 3 | kg |\n| A | C | 4 | kg |', '| A | B | 3 |']:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                normalize_stock_input({'text': header + rows})

    def test_kitchen_free_text_unchanged(self):
        data = {'text': 'SO MAJA\nGaram - 3 kg', 'stock_date': '2026-10-23'}
        self.assertEqual(normalize_stock_input(data), data)

    def test_cross_location_and_other_actions_rejected(self):
        self.assertEqual(stock_location(' koperasi '), 'KOPERASI')
        validate_change_scope('RECORD_STOCK_OPNAME', 'KOPERASI', {'location': 'KOPERASI'})
        for action in ['CREATE_PO', 'RECORD_GOODS_RECEIPT', 'CREATE_ACCOUNTANT_TRANSACTIONS', 'RECORD_VENDOR_PAYMENT', 'UPSERT_INVENTORY_ITEM_MASTER']:
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_change_scope(action, 'KOPERASI', {})
        with self.assertRaisesRegex(ValueError, 'Cross-location'):
            validate_change_scope('RECORD_STOCK_OPNAME', 'KOPERASI', {'location': 'MAJA'})

    def test_core_payload_keeps_location_and_strips_ui_only_fields(self):
        data = normalize_stock_input({'site': 'KOPERASI', 'text': sku_table(), 'zero_negative_quantities': True})
        body = stock_core_payload(data, 'KOPERASI', False)
        self.assertEqual(body['location'], 'KOPERASI')
        self.assertFalse(body['commit'])
        self.assertEqual(len(body['reviewed_items']), 105)
        self.assertNotIn('stock_input_summary', body)
        self.assertNotIn('site', body)


class StockWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_tools_prepare_in_koperasi_without_writing(self):
        from plugin_mcp.server import stock_opname_preview
        from plugin_mcp.v0186_tools import previewOrRecordSppgStockOpnameFromWhatsApp
        with patch('plugin_mcp.server.prepare_change', new_callable=AsyncMock, return_value={'status': 'PENDING'}) as prepare:
            result = await stock_opname_preview('KOPERASI', 'Garam - 1 kg', '2026-10-23')
        self.assertEqual(prepare.call_args.args[2], 'KOPERASI')
        self.assertFalse(result['committed'])
        with patch('plugin_mcp.approval_workflow.prepare_change', new_callable=AsyncMock, return_value={'status': 'PENDING'}) as prepare:
            await previewOrRecordSppgStockOpnameFromWhatsApp({'location': 'koperasi', 'text': 'Garam - 1 kg'})
        self.assertEqual(prepare.call_args.args[2], 'KOPERASI')
        self.assertFalse(prepare.call_args.args[1]['commit'])

    async def test_prepare_preview_and_execute_stay_on_koperasi(self):
        from plugin_mcp.approval_workflow import prepare_change, ChangeRequest, _execute
        requests = []
        async def core(method, path, **kwargs):
            if path.endswith('/operational-context'):
                return {'databaseReady': True}
            body = kwargs['json_body']
            requests.append(body)
            return {'canCommit': True, 'committed': body['commit'], 'location': body['location'],
                    'site': None, 'itemCount': len(body['reviewed_items']), 'items': []}
        conn = MagicMock()
        with patch('plugin_mcp.approval_workflow.core_request', new_callable=AsyncMock, side_effect=core), \
             patch('plugin_mcp.approval_workflow._db_ready'), patch('plugin_mcp.approval_workflow._ensure_table'), \
             patch('plugin_mcp.approval_workflow.connection', return_value=conn):
            proposal = await prepare_change('RECORD_STOCK_OPNAME', {'text': sku_table(), 'zero_negative_quantities': True}, 'KOPERASI', 'Synthetic preview regression')
            params = conn.__enter__.return_value.cursor.return_value.__enter__.return_value.execute.call_args.args[1]
            data = json.loads(params[5])
            result = await _execute(ChangeRequest(action='RECORD_STOCK_OPNAME', payload=data, site='KOPERASI', reason='Isolated fake execute regression'))
        self.assertEqual(proposal['status'], 'PENDING')
        self.assertEqual(proposal['preview']['itemCount'], 105)
        self.assertEqual(proposal['stockInputSummary']['zeroCorrectionCount'], 18)
        self.assertTrue(result['committed'])
        self.assertEqual([r['commit'] for r in requests], [False, True])
        self.assertEqual({r['location'] for r in requests}, {'KOPERASI'})

    async def test_koperasi_scope_cannot_execute_a_kitchen_finance_action(self):
        from plugin_mcp.approval_workflow import ChangeRequest, _execute
        change = ChangeRequest(action='CREATE_ACCOUNTANT_TRANSACTIONS', payload={}, site='KOPERASI', reason='Scope isolation')
        with patch('plugin_mcp.approval_workflow.core_request', new_callable=AsyncMock) as request:
            with self.assertRaises(ValueError):
                await _execute(change)
        request.assert_not_awaited()


class CoreStockContractTests(unittest.TestCase):
    def test_real_core_so_contract_stores_koperasi_with_no_kitchen_site(self):
        from backend.inventory_api import StockOpnameWhatsAppIn, stock_opname_whatsapp
        data = normalize_stock_input({'text': sku_table(), 'stock_date': '2026-10-23', 'zero_negative_quantities': True})
        conn = MagicMock()
        cur = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = [None, {'id': 9090}]
        def matched(name, masters):
            return {'inventoryItemCode': None, 'canonicalItemName': name, 'categoryCode': None, 'baseUnit': 'kg',
                    'classificationStatus': 'MATCHED', 'classificationMethod': 'EXACT_NAME', 'classificationConfidence': 1.0}
        with patch('backend.inventory_api.require_db'), patch('backend.inventory_api.connection', return_value=conn), \
             patch('backend.inventory_api.load_item_matchers', return_value=[]), \
             patch('backend.inventory_api.classify_item', side_effect=matched):
            preview = stock_opname_whatsapp(StockOpnameWhatsAppIn(**stock_core_payload(data, 'KOPERASI', False)))
            self.assertFalse(preview['committed'])
            self.assertFalse(any('insert into' in str(call.args[0]).lower() for call in cur.execute.call_args_list))
            result = stock_opname_whatsapp(StockOpnameWhatsAppIn(**stock_core_payload(data, 'KOPERASI', True)))
        writes = [(str(call.args[0]).lower(), call.args[1]) for call in cur.execute.call_args_list if 'insert into' in str(call.args[0]).lower()]
        parent = next(params for sql, params in writes if 'insert into stock_opnames(' in sql)
        children = [params for sql, params in writes if 'insert into stock_opname_items(' in sql]
        self.assertEqual(parent[:2], ('KOPERASI', None))
        self.assertEqual(len(children), 105)
        self.assertEqual(sum(params[6] == 0 for params in children), 18)
        self.assertEqual(children[-1][6], 105)
        self.assertTrue(all('inventory_movements' not in sql for sql, _ in writes))
        self.assertTrue(result['committed'])
        self.assertEqual(result['location'], 'KOPERASI')
        self.assertIsNone(result['site'])
        self.assertEqual(result['stockOpnameId'], 9090)


if __name__ == '__main__':
    unittest.main()
