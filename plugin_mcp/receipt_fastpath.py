"""Deterministic receipt input handling; no DB or operational writes."""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

_MONTHS = {name: i for i,name in enumerate(('januari','februari','maret','april','mei','juni','juli','agustus','september','oktober','november','desember'),1)}
_WEIGHT = re.compile(r'^\s*(?:[•*\-]\s*)?([0-9]+(?:[.,][0-9]+)?)\s*(kg|gram|g|liter|ltr|pcs)\s*$',re.I)
_QUANTITY = re.compile(r'(?<![\w.,])(-?\d+(?:[.,]\d+)?)\s*(kg|gram|g|liter|ltr|pcs)\b', re.I)


def _sectioned_report(text):
    """Read numbered WA item sections, retaining each weighing exactly once.

    Subtotals are checks, never additional stock. Ambiguous unlabelled quantities
    fail as a whole rather than returning a silently truncated item list.
    """
    lines = [re.sub(r'[^\w\s.,:/()+\-]', ' ', line.replace('\\', '')) .strip()
             for line in text.splitlines()]
    if not any(re.match(r'^\d+\s*[.)]\s*[A-Za-z]', line) for line in lines):
        return None
    sections = []
    current = None
    for line in lines:
        heading = re.match(r'^(\d+)\s*[.)]\s*(.+)$', line)
        if heading:
            body = heading[2].strip()
            quantity = _QUANTITY.search(body)
            name = (body[:quantity.start()] if quantity else body).strip(' .:-')
            if not name or re.search(r'\+|/|\bdan\b', name, re.I):
                raise ValueError('Tentukan nama dan alokasi jumlah untuk setiap barang')
            current = {'name':name, 'weights':[], 'total':None, 'number':int(heading[1])}
            sections.append(current)
            line = body[quantity.start():] if quantity else ''
        quantities = list(_QUANTITY.finditer(line))
        if not quantities:
            continue
        if current is None:
            raise ValueError('Ada timbangan sebelum nama barang; tentukan alokasinya')
        if re.match(r'^total\s*:', line, re.I):
            if len(quantities) != 1 or current['total'] is not None:
                raise ValueError('Subtotal barang tidak jelas')
            current['total'] = (_decimal(quantities[0][1]), quantities[0][2].lower())
        else:
            if len(quantities) != 1 or line[:quantities[0].start()].strip(' .:-'):
                raise ValueError('Ada jumlah tanpa alokasi barang yang jelas')
            current['weights'].append((_decimal(quantities[0][1]), quantities[0][2].lower()))
    if len({s['number'] for s in sections}) != len(sections):
        raise ValueError('Nomor barang berulang; periksa laporan')
    rows = []
    for section in sections:
        weights = section['weights']
        if not weights or len({unit for _,unit in weights}) != 1:
            raise ValueError('Barang membutuhkan timbangan dengan satuan yang konsisten: '+section['name'])
        total = sum((q for q,_ in weights), Decimal(0))
        unit = weights[0][1]
        if section['total'] and section['total'] != (total,unit):
            raise ValueError('Subtotal berbeda dari jumlah timbangan: '+section['name'])
        rows.append({'item_name':section['name'], 'received_qty':float(total), 'unit':unit,
                     'weighingCount':len(weights), 'exactQty':str(total)})
    return rows


def _decimal(value):
    try:
        out=Decimal(str(value).replace(',','.'))
    except InvalidOperation as exc:
        raise ValueError('Jumlah penerimaan bukan angka') from exc
    if not out.is_finite() or out<0: raise ValueError('Jumlah penerimaan harus angka nonnegatif')
    return out


def normalize_receipt_input(payload: dict) -> dict:
    """Accept original WA text, labelled single-item weighings, or explicit item rows.

    Never derive received weights from PO quantities. Dates without times remain
    explicitly marked DATE precision even though the legacy API stores a datetime.
    """
    data=deepcopy(payload)
    text=data.get('text') or data.get('raw_text') or data.get('message') or data.get('report_text')
    if not text and isinstance(data.get('items'),list):
        lines=[]
        for row in data['items']:
            name=row.get('item_name') or row.get('reported_item_name')
            qty=row.get('received_qty',row.get('qty'))
            unit=row.get('unit')
            if not name or qty is None or not unit: raise ValueError('Setiap barang membutuhkan nama, jumlah aktual dan satuan')
            lines.append(f'{name} - {_decimal(qty)} {unit}')
        text='\n'.join(lines)
    if not isinstance(text,str) or not text.strip(): raise ValueError('Kirim teks laporan asli atau rincian jumlah aktual barang')
    text=text.strip()
    data['text']=text
    sections = _sectioned_report(text)
    if sections:
        data['source_raw_text'] = data.get('source_raw_text') or text
        data['text'] = '\n'.join(f"{r['item_name']} - {r['exactQty']} {r['unit']}" for r in sections)
        summary = {'itemCount':len(sections), 'weighingCount':sum(r['weighingCount'] for r in sections),
                   'items':[{k:v for k,v in r.items() if k!='exactQty'} for r in sections]}
        if len({r['unit'] for r in sections}) == 1:
            summary.update(actualQty=float(sum((Decimal(r['exactQty']) for r in sections),Decimal(0))), unit=sections[0]['unit'])
        data['receipt_input_summary'] = summary
    weighings=[]
    for line in text.splitlines():
        m=_WEIGHT.fullmatch(re.sub(r'[*_]', '', line.strip()))
        if m: weighings.append((_decimal(m[1]),m[2].lower()))
    if weighings and not sections:
        mixed_named=any(re.search(r'\d[\d.,]*\s*(?:kg|gram|liter|ltr|pcs)\b',line,re.I) and not _WEIGHT.fullmatch(re.sub(r'[*_]', '', line.strip())) and not re.search(r'total\s+berat',line,re.I) for line in text.splitlines())
        if mixed_named: raise ValueError('Timbangan tanpa nama bercampur dengan item lain; tentukan alokasi per barang')
        header=re.search(r'rekap\s+kedatangan\s*[:-]?\s*([^\n]+)',text,re.I) or re.search(r'(?:penerimaan|barang\s+datang)\s*:\s*([^\n]+)',text,re.I)
        name=data.get('item_name_hint') or (header[1].strip(' *:') if header else None)
        if name and re.search(r'\+|/|\bdan\b',name,re.I):
            raise ValueError('Timbangan gabungan memerlukan alokasi jumlah per jenis barang')
        if name and len({u for _,u in weighings})==1:
            # A weighing section must describe ONE item. Explicit mixed-item
            # reports pass through unchanged to the Core parser.
            if re.search(r'\d\s*(?:kg|gram|liter|pcs)\b',name,re.I): name=None
            if name:
                total=sum((q for q,_ in weighings),Decimal(0))
                count=re.search(r'jumlah\s+kedatangan\s*:\s*(\d+)',text,re.I)
                declared=re.search(r'total\s+berat\s*:\s*(\d+(?:[.,]\d+)?)',text,re.I)
                if count and int(count[1])!=len(weighings): raise ValueError('Jumlah data timbangan berbeda dari jumlah kedatangan tertulis')
                if declared and _decimal(declared[1])!=total: raise ValueError(f'Total tertulis berbeda dari jumlah timbangan: {total}')
                name=re.sub(r'\bfilet\b','Fillet',name,flags=re.I)
                data['source_raw_text']=data.get('source_raw_text') or text
                data['text']=f'{name} - {total} {weighings[0][1]}'
                data['receipt_input_summary']={'weighingCount':len(weighings),'actualQty':float(total),'unit':weighings[0][1]}
    received=data.get('received_at') or data.get('received_date')
    if not received:
        m=re.search(r'\b(\d{1,2})\s+('+'|'.join(_MONTHS)+r')\s+(20\d{2})\b',text,re.I)
        if m: received=date(int(m[3]),_MONTHS[m[2].lower()],int(m[1])).isoformat()
    if received:
        value=str(received)
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            day=date.fromisoformat(value)
            data['received_at']=datetime(day.year,day.month,day.day,tzinfo=ZoneInfo('Asia/Jakarta')).isoformat()
            data['received_time_precision']='DATE'
        else:
            dt=datetime.fromisoformat(value.replace('Z','+00:00'))
            if dt.tzinfo is None: dt=dt.replace(tzinfo=ZoneInfo('Asia/Jakarta'))
            data['received_at']=dt.isoformat()
    for key in ('received_date','item_name_hint'):
        data.pop(key,None)
    return data


def compact_knowledge(body: dict) -> dict:
    """Return rules needed for judgment; omit unrelated ledgers, raw chat and old policy prose."""
    live=body.get('liveContext') or {}
    learned=live.get('learnedKnowledge') or []
    if isinstance(learned,dict): learned=learned.get('items') or []
    return {'loaded':bool(body.get('databaseReady')),'canonicalVersion':(body.get('canonicalKnowledge') or {}).get('version'),
            'canonicalFacts':(body.get('canonicalKnowledge') or {}).get('canonicalFacts',{}),
            'confirmedKnowledge':[r for r in learned if r.get('status')=='CONFIRMED'],
            'vendorRules':live.get('vendorRules') or [],'sectionErrors':body.get('sectionErrors') or {}}
