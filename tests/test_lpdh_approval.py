"""Synthetic-only approval/default/Drive failure contracts."""
import base64
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import date
from io import BytesIO
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import test_generated_document_api as fixture
from backend import lpdh_api as api
from backend.lpdh_approval import incentive_defaults, attach_approval, approval_hash, print_copy, render_approval
from openpyxl import Workbook, load_workbook
from PIL import Image
from fastapi import HTTPException


class ApprovalTests(unittest.TestCase):
    def test_defaults_update_automatic_values_and_preserve_manual_zero(self):
        result = incentive_defaults({}, 5572000, '2026-10-05', 'MAJA', '001/KW/2026')
        self.assertEqual(result['incentive']['paymentDate'], '2026-10-05')
        self.assertEqual(result['incentive']['receiptSigned'], 'Ya')
        self.assertEqual(result['incentive']['paidAmount'], 5572000)
        self.assertEqual(incentive_defaults(result, 6000000, '2026-10-05', 'MAJA')['incentive']['paidAmount'], 6000000)
        manual = {'incentive': {'paidAmount': 0, 'statementAmount': 100, 'paymentDate': '2026-10-06'}}
        changed = incentive_defaults(manual, 5572000, '2026-10-05', 'MAJA')
        self.assertEqual(changed['incentive']['paidAmount'], 0)
        self.assertEqual(changed['incentive']['statementAmount'], 100)
        self.assertEqual(changed['incentive']['paymentDate'], '2026-10-06')
        historic = {'_historicalGeneratedSnapshot': True, 'incentive': {}}
        self.assertEqual(incentive_defaults(historic, 100, '2026-10-05', 'MAJA'), historic)

    def test_links_manual_preservation_and_revision_history(self):
        archive = {'driveUri': 'https://drive.google.com/file/d/approval/view'}
        original = {'incentive': {}}
        final = attach_approval(original, archive, 'hash', 'OWNER', 'now')
        self.assertEqual(original, {'incentive': {}})
        self.assertEqual(final['incentive']['evidenceLink'], archive['driveUri'])
        self.assertEqual(approval_hash({}, original, '2026-10-05', {}), approval_hash({}, final, '2026-10-05', {}))
        final['incentive']['evidenceLink'] = 'https://manual.example/paid.pdf'
        next_version = attach_approval(final, {'driveUri': 'https://drive.google.com/file/d/new/view'}, 'hash2', 'OWNER', 'later')
        self.assertEqual(next_version['incentive']['evidenceLink'], 'https://manual.example/paid.pdf')
        self.assertEqual(len(next_version['_approvalHistory']), 1)
        with self.assertRaises(ValueError):
            attach_approval(original, {'driveUri': ''}, 'hash', 'OWNER', 'now')

    def test_print_copy_preserves_formulas_layout_and_only_j_visible(self):
        wb = Workbook(); wb.active.title = 'Identitas'; wb.active['B6'] = 'TEST'
        ws = wb.create_sheet('J_Pengesahan'); ws.merge_cells('A1:F1'); ws['A1'] = 'LEMBAR PENGESAHAN'
        ws['D5'] = '=Identitas!B6'; ws.column_dimensions['B'].width = 30
        source = BytesIO(); wb.save(source); raw = source.getvalue()
        picture = BytesIO(); Image.new('RGBA', (120, 40), (0, 0, 0, 255)).save(picture, 'PNG')
        asset = 'data:image/png;base64,' + base64.b64encode(picture.getvalue()).decode()
        printed = load_workbook(BytesIO(print_copy(raw, {'approvalSppgSignature': asset})))
        self.assertEqual(printed['J_Pengesahan']['D5'].value, '=Identitas!B6')
        self.assertEqual(printed['J_Pengesahan'].column_dimensions['B'].width, 30)
        self.assertEqual(printed['Identitas'].sheet_state, 'hidden')
        self.assertEqual(printed['J_Pengesahan'].sheet_state, 'visible')
        self.assertEqual(len(printed['J_Pengesahan']._images), 1)
        self.assertEqual(load_workbook(BytesIO(raw))['Identitas'].sheet_state, 'visible')
        wb['Identitas']['A1'] = '=WEBSERVICE("https://example.com")'
        bad = BytesIO(); wb.save(bad)
        with self.assertRaises(ValueError): print_copy(bad.getvalue(), {})

    def test_missing_converter_fails_closed(self):
        with patch('backend.lpdh_approval.shutil.which', return_value=None):
            with self.assertRaises(ValueError): render_approval(b'', {})

    def test_finalize_failure_stale_and_idempotence(self):
        request = SimpleNamespace(state=SimpleNamespace(sppg_role='OWNER'))
        self.commits = 0; self.writes = []
        @contextmanager
        def connection(): yield self
        self.cursor = lambda: connection()
        self.execute = lambda *args: self.writes.append(args)
        self.commit = lambda: setattr(self, 'commits', self.commits + 1)
        daily = {'incentive': {'receiptNo': '001/KW/2026', 'proofNo': 'BYR-TEST'}}
        inputs = ({'signers': [{'name':'A'},{'name':'B'},{'name':'C'}]}, daily, {}, b'xlsx', 'a'*64, {'effective': True})
        payload = api.ApprovalIn(site='MAJA', service_date=date(2026,10,5), expected_hash='a'*64)
        with ExitStack() as stack:
            for name, value in {'connection':connection, '_approval_inputs':lambda *a:deepcopy(inputs), 'render_approval':lambda *a:b'pdf', 'claim_number':lambda *a:None}.items():
                stack.enter_context(patch.object(api, name, value))
            stack.enter_context(patch.object(fixture.api, 'daily_lock', lambda *a:None))
            with patch('backend.accountant_drive.upload_accountant_artifact', side_effect=RuntimeError('failed')):
                with self.assertRaises(HTTPException) as error: api.approval_finalize(payload, request)
                self.assertEqual(error.exception.status_code, 502)
                self.assertEqual(self.commits, 0); self.assertEqual(self.writes, [])
            payload.expected_hash = 'b'*64
            with self.assertRaises(HTTPException) as error: api.approval_finalize(payload, request)
            self.assertEqual(error.exception.status_code, 409)
            payload.expected_hash = 'a'*64
            response = api.approval_finalize(payload, request)
            self.assertEqual(self.commits, 1)
            self.assertEqual(response['approval']['status'], 'FINAL')
            daily['_approval'] = response['approval']
            response = api.approval_finalize(payload, request)
            self.assertTrue(response['alreadyFinal']); self.assertEqual(self.commits, 1)
        with self.assertRaises(HTTPException) as error:
            api.approval_finalize(payload, SimpleNamespace(state=SimpleNamespace(sppg_role='CEMPLANG')))
        self.assertEqual(error.exception.status_code, 403)


if __name__ == '__main__': unittest.main()
