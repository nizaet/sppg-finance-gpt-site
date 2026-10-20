from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import po_warehouse_stock_api as api
from backend.item_taxonomy import stock_type


class Cursor:
    def __init__(self, site='MAJA', status='ACTIVE', prior=None):
        self.calls=[]; self.rows=[]; self.site=site; self.status=status; self.prior=prior
    def execute(self, sql, params=()):
        self.calls.append((sql,params));self.rows=[]
        if 'select details' in sql: self.rows=[{'details':self.prior}] if self.prior else []
        elif 'select psi.item_name' in sql:self.rows=[dict(item_name='Jeruk Medan',unit='kg',site=self.site,status=self.status,distribution_date=api.datetime.now(api.ZoneInfo('Asia/Jakarta')).date()+timedelta(days=2))]
        elif 'returning id' in sql:self.rows=[{'id':51}]
    def fetchone(self):return self.rows[0] if self.rows else None
    def __enter__(self):return self
    def __exit__(self,*_):pass


@pytest.fixture
def setup(monkeypatch):
    cur=Cursor()
    class Connection:
        committed=False
        def cursor(self):return cur
        def commit(self):self.committed=True
    conn=Connection()
    @contextmanager
    def connection():yield conn
    projection={'items':[{'item_name':'Jeruk Medan','stock_type_code':'JERUK_MEDAN','unit':'kg','actual_balance':10,'available_for_po':6,'planned_depletion':4}]}
    monkeypatch.setattr(api,'connection',connection)
    monkeypatch.setattr(api,'require_db',lambda:None)
    monkeypatch.setattr(api,'load_item_matchers',lambda *a:[])
    monkeypatch.setattr(api,'inventory_balances_v2',lambda **kw:projection)
    monkeypatch.setattr(api,'invalidate_projection_cache',lambda *a:None)
    day=api.datetime.now(api.ZoneInfo('Asia/Jakarta')).date()
    payload=api.PoWarehouseStockIn(site='MAJA',planning_snapshot_item_id=1,distribution_date=day+timedelta(days=2),cooking_date=day+timedelta(days=1),unit='kg',target_balance=15,expected_actual_balance=10,request_id=uuid4())
    return cur,conn,projection,payload


@pytest.mark.parametrize('site',['MAJA','CEMPLANG'])
@pytest.mark.parametrize('target',[15,0,10])
def test_saves_physical_stock_delta_and_before_cooking_anchor(setup,site,target):
    cur,conn,projection,payload=setup
    cur.site=site;payload.site=site;payload.target_balance=Decimal(target)
    result=api.confirm_po_warehouse_stock(payload)
    assert result['committed'] and conn.committed
    assert result['targetBalance']==str(target)
    insert=next(params for sql,params in cur.calls if 'insert into inventory_movements' in sql)
    assert insert[1]=='Jeruk Medan' and insert[2]==abs(target-10)
    assert insert[4:6]==(('MANUAL_ADJUSTMENT',site) if target>10 else (site,'MANUAL_ADJUSTMENT') if target<10 else (site,site))
    assert json.loads(insert[-1])['stock_check_timing']=='BEFORE_COOKING'
    assert any('insert into event_audit_log' in sql for sql,_ in cur.calls)


def test_stale_stock_does_not_write(setup):
    cur,conn,projection,payload=setup;projection['items'][0]['actual_balance']=12
    with pytest.raises(HTTPException) as error:api.confirm_po_warehouse_stock(payload)
    assert error.value.status_code==409 and not conn.committed
    assert not any('insert into inventory_movements' in sql for sql,_ in cur.calls)


@pytest.mark.parametrize('site,status',[('CEMPLANG','ACTIVE'),('MAJA','SUPERSEDED')])
def test_wrong_site_or_replaced_plan_does_not_write(setup,site,status):
    cur,conn,projection,payload=setup;cur.site=site;cur.status=status
    with pytest.raises(HTTPException):api.confirm_po_warehouse_stock(payload)
    assert not conn.committed


def test_retry_returns_same_result_without_a_second_stock_write(setup):
    cur,conn,projection,payload=setup
    result=api.confirm_po_warehouse_stock(payload)
    cur.calls=[];cur.prior=result
    assert api.confirm_po_warehouse_stock(payload)['duplicate']
    assert not any('insert into inventory_movements' in sql for sql,_ in cur.calls)


def test_retry_with_different_target_is_rejected(setup):
    cur,conn,projection,payload=setup
    cur.prior=api.confirm_po_warehouse_stock(payload);payload.target_balance=Decimal(16)
    with pytest.raises(HTTPException) as error:api.confirm_po_warehouse_stock(payload)
    assert error.value.status_code==409


@pytest.mark.parametrize('value',[-1,'NaN','Infinity','1.00001'])
def test_invalid_target_is_rejected(setup,value):
    payload=setup[-1].model_dump();payload['target_balance']=value
    with pytest.raises(ValidationError):api.PoWarehouseStockIn(**payload)


def test_jeruk_identity_excludes_other_citrus():
    assert stock_type('Jeruk')['code']==stock_type('Jeruk Medan')['code']
    for name in ['Jeruk Nipis','Jeruk Lemon','Jeruk Bali','Daun Jeruk']:
        assert stock_type(name)['code']!=stock_type('Jeruk')['code']


def test_fresh_and_dried_chili_have_distinct_stock_identities():
    assert stock_type('Cabai Merah Kering')['code'] != stock_type('Cabai Merah')['code']
