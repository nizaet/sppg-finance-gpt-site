"""Receipt comparison and local-day boundaries; no writes or database access."""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


def jakarta_day_bounds(day):
    start=datetime.combine(day,time.min,tzinfo=ZoneInfo('Asia/Jakarta'))
    return start,start+timedelta(days=1)


def receipt_signature(rows, normalize_name, normalize_unit):
    totals=defaultdict(Decimal)
    for row in rows:
        name=normalize_name(str(row.get('reported_item_name') or row.get('item_name') or ''))
        unit=normalize_unit(row.get('unit'))
        try:
            quantity=Decimal(str(row.get('received_qty')))
        except (InvalidOperation,ValueError,TypeError):
            return None
        if not name or not unit or not quantity.is_finite() or quantity<0:
            return None
        totals[(name,unit)]+=quantity
    return tuple(sorted((name,unit,qty) for (name,unit),qty in totals.items())) or None
