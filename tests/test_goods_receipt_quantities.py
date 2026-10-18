"""Run SQL tests against a disposable PostgreSQL via SPPG_RECEIVING_TEST_DATABASE_URL.

Each test owns and removes an isolated schema; no operational tables are touched.
"""
import os
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row
from pydantic import ValidationError

from backend import po_receiving_confirmation_api as api


@pytest.mark.parametrize('value', [-1, 'NaN', 'Infinity', '1.00001'])
def test_invalid_actual_quantity(value):
    with pytest.raises(ValidationError):
        api.ActualReceiptLine(purchase_order_item_id=1, received_qty=value, expected_received_qty=0)


@pytest.fixture
def database(monkeypatch):
    url = os.getenv('SPPG_RECEIVING_TEST_DATABASE_URL')
    if not url:
        pytest.skip('requires a disposable PostgreSQL test database')
    schema = 'receipt_test_' + uuid4().hex
    conn = psycopg.connect(url, row_factory=dict_row, autocommit=True)
    conn.execute(f'create schema {schema}')
    conn.execute(f'set search_path to {schema}')
    root = Path(__file__).resolve().parents[1]
    try:
        for name in ['staging_v05.sql', 'core_domain_v05.sql', 'inventory_ledger_v014.sql']:
            conn.execute((root / 'schema' / name).read_text())
        conn.execute('create table planning_snapshots (id bigserial primary key); create table planning_snapshot_items (id bigserial primary key)')
        for name in ['operational_receiving_v012.sql', 'vendor_payables_v013.sql']:
            conn.execute((root / 'schema' / name).read_text())
        conn.execute("insert into purchase_orders(id,po_code,site,vendor_code,status) values (1,'TEST','MAJA','HOLIL','SENT')")
        conn.execute("insert into purchase_order_items(id,purchase_order_id,item_name,po_qty,unit) values (11,1,'Wortel',10,'kg')")

        @contextmanager
        def connection():
            conn.execute('begin')
            try:
                yield conn
            finally:
                conn.execute('rollback')
        monkeypatch.setattr(api, 'connection', connection)
        monkeypatch.setattr(api, 'require_db', lambda: None)
        monkeypatch.setattr(api, '_invalidate_stock', lambda site: None)
        yield conn
    finally:
        conn.execute('rollback')
        conn.execute('set search_path to public')
        conn.execute(f'drop schema {schema} cascade')
        conn.close()


def receive(qty, expected=0, request_id=None):
    return api.confirm_po_receiving(1, api.PoReceivingConfirmIn(mode='ACTUAL', request_id=request_id or uuid4(), items=[dict(purchase_order_item_id=11, received_qty=qty, expected_received_qty=expected)]))


def correction(database, receipt_id, qty, rejected=0, site='MAJA'):
    row = database.execute('select * from goods_receipt_items where goods_receipt_id=%s', (receipt_id,)).fetchone()
    return api.ReceiptCorrectionIn(site=site, request_id=uuid4(), reason='Koreksi aktual dari operator', items=[dict(receipt_item_id=row['id'], received_qty=qty, rejected_qty=rejected, expected_received_qty=row['received_qty'], expected_rejected_qty=row['rejected_qty'], expected_updated_at=row['updated_at'])])


def balance(database, site='MAJA'):
    return database.execute('select coalesce(sum(case when to_location=%s then qty else -qty end),0) as qty from inventory_movements where to_location=%s or from_location=%s', (site,site,site)).fetchone()['qty']


def test_partial_delivery_and_idempotent_retry(database):
    key = uuid4()
    result = receive('6.25', request_id=key)
    assert result['purchaseOrderStatus'] == 'PARTIAL_RECEIVED'
    receive('6.25', request_id=key)
    assert balance(database) == Decimal('6.25')
    assert database.execute('select count(*) as n from goods_receipts').fetchone()['n'] == 1


def test_correction_preserves_original_stock_and_retry(database):
    rid = receive(10)['receiptId']
    original = database.execute('select * from inventory_movements').fetchone()
    payload = correction(database, rid, '8.5', 1)
    result = api.correct_goods_receipt(rid, payload)
    assert result['purchaseOrderStatus'] == 'PARTIAL_RECEIVED'
    assert balance(database) == Decimal('7.5')
    assert api.correct_goods_receipt(rid, payload)['duplicate']
    assert balance(database) == Decimal('7.5')
    movements = database.execute('select * from inventory_movements order by id').fetchall()
    assert movements[0] == original
    assert movements[1]['occurred_at'] == original['occurred_at']
    assert movements[1]['from_location'] == 'MAJA'
    assert movements[1]['to_location'] == 'VENDOR:HOLIL'
    assert database.execute('select count(*) as n from event_audit_log').fetchone()['n'] == 1


def test_zero_then_restore_then_complete(database):
    rid = receive(10)['receiptId']
    result = api.correct_goods_receipt(rid, correction(database, rid, 0))
    assert result['purchaseOrderStatus'] == 'SENT'
    assert balance(database) == 0
    api.correct_goods_receipt(rid, correction(database, rid, 8))
    assert balance(database) == 8
    assert api.confirm_po_receiving(1, api.PoReceivingConfirmIn())['purchaseOrderStatus'] == 'RECEIVED'
    assert balance(database) == 10


def test_all_as_po_can_be_used_again_after_mistaken_confirmation(database):
    rid = api.confirm_po_receiving(1, api.PoReceivingConfirmIn())['receiptId']
    api.correct_goods_receipt(rid, correction(database, rid, 0))
    api.confirm_po_receiving(1, api.PoReceivingConfirmIn())
    assert balance(database) == 10


def test_overdelivery_does_not_change_po(database):
    receive(12)
    assert balance(database) == 12
    assert database.execute('select po_qty from purchase_order_items').fetchone()['po_qty'] == 10


def test_stale_correction_rolls_back_without_extra_stock(database):
    rid = receive(10)['receiptId']
    stale = correction(database, rid, 5)
    api.correct_goods_receipt(rid, correction(database, rid, 8))
    with pytest.raises(HTTPException) as error:
        api.correct_goods_receipt(rid, stale)
    assert error.value.status_code == 409
    assert balance(database) == 8


@pytest.mark.parametrize('site,qty,rejected,expected', [('CEMPLANG',8,0,400), ('MAJA',3,4,400)])
def test_wrong_site_or_excess_reject_cannot_write(database, site, qty, rejected, expected):
    rid = receive(10)['receiptId']
    with pytest.raises(HTTPException) as error:
        api.correct_goods_receipt(rid, correction(database,rid,qty,rejected,site))
    assert error.value.status_code == expected
    assert balance(database) == 10


def test_linked_paid_invoice_unchanged_and_flagged(database):
    rid = receive(10)['receiptId']
    database.execute("insert into vendor_invoices(vendor_code,site,goods_receipt_id,net_amount,payable_status) values ('HOLIL','MAJA',%s,100000,'PAID')", (rid,))
    result = api.correct_goods_receipt(rid, correction(database,rid,8))
    assert result['invoiceReviewRequired'] and len(result['linkedInvoiceIds']) == 1
    invoice = database.execute('select * from vendor_invoices').fetchone()
    assert invoice['net_amount'] == 100000 and invoice['payable_status'] == 'PAID'


def test_koperasi_correction_returns_delta_to_origin(database):
    database.execute("update purchase_orders set vendor_code='KOPERASI'")
    rid = receive(10)['receiptId']
    api.correct_goods_receipt(rid, correction(database,rid,6))
    assert balance(database) == 6
    assert balance(database,'KOPERASI') == -6


def test_zero_original_row_posts_once_when_corrected_positive(database):
    rid = receive(10)['receiptId']
    database.execute('insert into goods_receipt_items(goods_receipt_id,purchase_order_item_id,received_qty,accepted_qty,rejected_qty,unit) values (%s,11,0,0,0,\'kg\')', (rid,))
    row = database.execute('select * from goods_receipt_items order by id desc limit 1').fetchone()
    payload=api.ReceiptCorrectionIn(site='MAJA',request_id=uuid4(),reason='Barang tambahan benar-benar datang',items=[dict(receipt_item_id=row['id'],received_qty=2,rejected_qty=0,expected_received_qty=0,expected_rejected_qty=0)])
    api.correct_goods_receipt(rid,payload)
    with database.cursor() as cur:
        api.commit_receipt_stock(cur,rid,'MAJA')
    assert balance(database) == 12
