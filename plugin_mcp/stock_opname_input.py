"""Location-scoped SO inputs. Preserve original tables and explicit corrections."""
from copy import deepcopy
from decimal import Decimal
import re
import math
from backend.stock_opname_parser import canonical_unit

STOCK_LOCATIONS = frozenset({'MAJA', 'CEMPLANG', 'KOPERASI'})


def stock_location(value):
    location = str(value or '').strip().upper()
    if location not in STOCK_LOCATIONS:
        raise ValueError('stock location must be KOPERASI, MAJA or CEMPLANG')
    return location


def validate_change_scope(action, site, payload):
    if site == 'GLOBAL' and action != 'UPSERT_INVENTORY_ITEM_MASTER':
        raise ValueError('GLOBAL is only allowed for the shared inventory master')
    if site == 'KOPERASI' and action != 'RECORD_STOCK_OPNAME':
        raise ValueError('KOPERASI change scope is only allowed for stock opname')
    if payload.get('site') not in (None, '', site):
        raise ValueError('Cross-site payload and change.site mismatch')
    if action == 'RECORD_STOCK_OPNAME' and payload.get('location') not in (None, '', site):
        raise ValueError('Cross-location stock opname is not allowed')


def _cells(line):
    return [value.strip() for value in line.strip().strip('|').split('|')]


def _header(value):
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', value.lower()).split())


def normalize_stock_input(payload):
    data = deepcopy(payload)
    zero_negatives = data.pop('zero_negative_quantities', False)
    if type(zero_negatives) is not bool:
        raise ValueError('zero_negative_quantities must be true or false')
    # Reviewed rows already contain the operator's edits/selection; never rebuild them.
    if data.get('reviewed_items') is not None:
        rows = [row for row in data['reviewed_items'] if row.get('include', True)]
        for row in rows:
            if not math.isfinite(float(row['qty'])) or float(row['qty']) < 0:
                raise ValueError('Reviewed stock quantities must be finite and nonnegative')
        if data.get('stock_input_summary'):
            selected = {row.get('client_key'): row for row in rows}
            summary = data['stock_input_summary']
            summary['rowCount'] = len(rows)
            summary['zeroCorrections'] = [row for row in summary.get('zeroCorrections', [])
                                          if row['sku'] in selected and float(selected[row['sku']]['qty']) == 0]
            summary['zeroCorrectionCount'] = len(summary['zeroCorrections'])
        return data
    text = str(data.get('text') or '')
    columns, column_count = None, None
    rows, corrections, seen = [], [], set()
    for raw in text.splitlines():
        if not raw.strip().startswith('|'):
            continue
        cells = _cells(raw)
        names = [_header(cell) for cell in cells]
        if {'sku', 'nama barang', 'sisa stok gudang', 'satuan'} <= set(names):
            if columns is not None:
                raise ValueError('SO must contain one SKU table; review multiple tables separately')
            if len(names) != len(set(names)):
                raise ValueError('Ambiguous duplicate SO table columns')
            column_count = len(cells)
            columns = {name: names.index(name) for name in ('sku', 'nama barang', 'sisa stok gudang', 'satuan')}
            continue
        if columns is None or all(re.fullmatch(r'[:\-\s]+', cell or '-') for cell in cells):
            continue
        if len(cells) != column_count:
            raise ValueError('Incomplete SKU table row: ' + raw[:120])
        sku, name, amount, unit = (cells[columns[key]] for key in ('sku', 'nama barang', 'sisa stok gudang', 'satuan'))
        if not sku or not name or not unit:
            raise ValueError('SKU, item name and unit are required for every SO row')
        if sku.upper() in seen:
            raise ValueError('Duplicate SKU in SO: ' + sku)
        seen.add(sku.upper())
        amount = amount.replace('**', '').strip()
        if not re.fullmatch(r'-?\d+(?:[.,]\d+)?', amount):
            raise ValueError('Invalid stock quantity for ' + sku)
        quantity = Decimal(amount.replace(',', '.'))
        if not math.isfinite(float(quantity)):
            raise ValueError('Stock quantity must be finite for ' + sku)
        if quantity < 0:
            if not zero_negatives:
                raise ValueError('Negative physical stock for ' + sku + '; supply reviewed nonnegative quantities or explicitly approve zero_negative_quantities=true')
            corrections.append({'sku': sku, 'itemName': name, 'before': str(quantity), 'after': 0})
            quantity = Decimal(0)
        rows.append({'client_key': sku, 'include': True, 'raw_item_name': name,
                     'qty': float(quantity), 'unit': {'btl': 'botol'}.get(unit.lower(), unit),
                     'raw_line': raw})
    if columns is not None:
        if not rows:
            raise ValueError('SKU table contains no stock rows')
        data['reviewed_items'] = rows
        data['stock_input_summary'] = {'format': 'SKU_TABLE', 'rowCount': len(rows),
                                     'zeroCorrections': corrections, 'zeroCorrectionCount': len(corrections)}
    return data


def stock_core_payload(payload, location, commit):
    data = deepcopy(payload)
    data.pop('site', None)
    data.pop('stock_input_summary', None)
    data.pop('zero_negative_quantities', None)
    data.update(location=stock_location(location), commit=commit)
    return data


def validated_stock_result(result, payload):
    """Verify every table row before discarding obsolete free-text parser warnings."""
    if payload.get('stock_input_summary', {}).get('format') != 'SKU_TABLE':
        return result
    expected = [row for row in payload['reviewed_items'] if row.get('include', True)]
    actual = result.get('items', [])
    if result.get('itemCount') != len(expected) or len(actual) != len(expected):
        raise ValueError('Core stock preview did not preserve every selected SKU row')
    for source, item in zip(expected, actual):
        if (item.get('clientKey') != source['client_key']
                or item.get('itemName') != source['raw_item_name'].strip()
                or Decimal(str(item.get('qty'))) != Decimal(str(source['qty']))
                or item.get('unit') != canonical_unit(source['unit'])):
            raise ValueError('Core stock preview differs from reviewed SKU ' + source['client_key'])
    result = dict(result)
    result['warnings'] = [warning for warning in result.get('warnings', [])
                          if not warning.startswith(('Satuan tidak tertulis;', 'Duplikat '))]
    result['stockInputSummary'] = payload['stock_input_summary']
    return result
