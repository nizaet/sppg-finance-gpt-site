"""Separate document numbers and editable print metadata; source invoices stay locked."""
import json
from datetime import date, timedelta

KINDS = {'PO': -2, 'SJ': -1, 'CKL': -1, 'KUI': 1}
ROMAN = ['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII']


def document_dates(service_date):
    day = date.fromisoformat(str(service_date))
    return {kind:(day+timedelta(days=offset)).isoformat() for kind,offset in KINDS.items()}


def ensure_package(cur, row):
    if row['document_type'] not in {'BAHAN_BAKU','OPERASIONAL'} or row['status'] != 'FINAL':
        return None
    # Site lock serializes allocation and makes repeated finalization idempotent.
    cur.execute('select pg_advisory_xact_lock(hashtext(%s))', ('lpdh-delivery:'+row['site'],))
    cur.execute('select * from lpdh_delivery_packages where document_id=%s', (row['id'],))
    existing=cur.fetchone()
    if existing: return existing
    dates=document_dates(row['service_date'])
    numbers={}
    for kind,day in dates.items():
        dt=date.fromisoformat(day)
        period=str(dt.year) if kind=='KUI' else day[:7]
        cur.execute('''insert into lpdh_delivery_counters(site,kind,period,value) values(%s,%s,%s,1)
          on conflict(site,kind,period) do update set value=lpdh_delivery_counters.value+1 returning value''',
          (row['site'],kind,period))
        seq=f"{cur.fetchone()['value']:03d}"
        if kind=='KUI':
            category='BB' if row['document_type']=='BAHAN_BAKU' else 'OP'
            numbers[kind]=f'{seq}/KUI.Banper/{category}/{ROMAN[dt.month-1]}/{dt.year}'
        elif kind=='PO': numbers[kind]=f'PO/{dt.year}/{ROMAN[dt.month-1]}/{seq}'
        else: numbers[kind]=f'{kind}/{dt.year}{dt.month:02d}/{seq}'
    cur.execute('select settings from lpdh_delivery_packages where site=%s order by updated_at desc,document_id desc limit 1', (row['site'],))
    defaults=(cur.fetchone() or {}).get('settings') or {}
    defaults={key:value for key,value in defaults.items() if key!='paymentFor'}
    cur.execute('''insert into lpdh_delivery_packages(document_id,site,service_date,numbers,settings)
      values(%s,%s,%s,%s::jsonb,%s::jsonb) returning *''', (row['id'],row['site'],row['service_date'],json.dumps(numbers),json.dumps(defaults)))
    return cur.fetchone()
