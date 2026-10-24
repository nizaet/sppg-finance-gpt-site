"""Deterministic shared calculator ingredient -> warehouse master mapping. Never stock/price writes."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from backend.stock_opname_parser import normalize_name, canonical_unit
from backend.item_taxonomy import stock_type


def base_unit(unit):
    unit = canonical_unit(unit)
    return 'kg' if unit == 'gr' else unit


def plan_mapping(masters, sources):
    by_name = {}
    by_type = {}
    for master in masters:
        for name in [master['canonical_name'], *(master.get('aliases') or [])]:
            by_name.setdefault(normalize_name(name), []).append(master)
        kind = stock_type(master['canonical_name'])
        if kind['method'] == 'ITEM_TYPE_RULE' and master.get('active') is not False:
            by_type.setdefault(kind['code'], []).append(master)
    units = {}
    for row in sources:
        unit = base_unit(row.get('unit'))
        if unit:
            units.setdefault(normalize_name(row['name']), set()).add(unit)
    creations, aliases, unresolved = [], [], []
    for row in sorted(sources, key=lambda r: (normalize_name(r['name']), r.get('source',''))):
        name = row['name'].strip(); normalized = normalize_name(name)
        candidates = {m['code']:m for m in by_name.get(normalized, [])}
        declared = units.get(normalized, set())
        if len(declared) > 1:
            unresolved.append({'name':name,'reason':'CONFLICTING_UNITS','units':sorted(declared)}); continue
        unit = next(iter(declared), None)
        if len(candidates) > 1:
            unresolved.append({'name':name,'reason':'AMBIGUOUS_ALIAS'}); continue
        match = next(iter(candidates.values()), None)
        if match and (match.get('active') is False or (unit and base_unit(match.get('base_unit')) != unit)):
            unresolved.append({'name':name,'reason':'INACTIVE_OR_UNIT_CONFLICT'}); continue
        if not match and unit:
            kind = stock_type(name)
            typed = [m for m in by_type.get(kind['code'],[]) if base_unit(m.get('base_unit')) == unit] if kind['method']=='ITEM_TYPE_RULE' else []
            if len(typed)>1:
                unresolved.append({'name':name,'reason':'AMBIGUOUS_TYPE'}); continue
            if len(typed)==1: match=typed[0]
        if not match:
            if not unit:
                unresolved.append({'name':name,'reason':'UNIT_REQUIRED','source':row.get('source')}); continue
            code='CALC_'+hashlib.sha256(normalized.encode()).hexdigest()[:20].upper()
            match={'code':code,'canonical_name':name,'base_unit':unit,'active':True,'aliases':[],'source':row.get('source')}
            creations.append(match)
            kind=stock_type(name)
            if kind['method']=='ITEM_TYPE_RULE': by_type.setdefault(kind['code'],[]).append(match)
        by_name[normalized]=[match]
        if normalized != normalize_name(match['canonical_name']) and name not in match.get('aliases',[]):
            aliases.append({'code':match['code'],'alias':name});match.setdefault('aliases',[]).append(name)
    return {'creations':creations,'aliases':aliases,'unresolved':list({(x['name'],x['reason']):x for x in unresolved}.values())}


def calculator_sources():
    from backend.calculator_data_api import _load_master_state
    def read(args):
        site,kind=args
        _,state=_load_master_state(site,kind)
        rows=[]
        for key,value in state.items():
            if not isinstance(value,dict): continue
            name=str(value.get('name') or key).strip()
            source=f'{site}:{kind}:{key}'
            if kind=='RECIPES':
                for ingredient in value.get('ingredients') or []:
                    if isinstance(ingredient,dict) and ingredient.get('name'):
                        rows.append({'name':str(ingredient['name']),'unit':ingredient.get('unit') or ('gr' if ingredient.get('quantity_gr') is not None else None),'source':source})
            elif name:
                rows.append({'name':name,'unit':value.get('unit') or ('gr' if kind=='BUMBU' else None),'source':source})
        return rows
    # Fetch every authoritative source before any master mutation; failures cannot silently use stale data.
    with ThreadPoolExecutor(max_workers=8) as pool:
        return [row for rows in pool.map(read,[(s,k) for s in ('MAJA','CEMPLANG') for k in ('PRICES','GRAMASI','RECIPES','BUMBU')]) for row in rows]


def sync_sources(cur, sources):
    cur.execute("select pg_advisory_xact_lock(hashtextextended('shared-calculator-inventory-master',0))")
    cur.execute('''select m.code,m.canonical_name,m.base_unit,m.active,
        coalesce(json_agg(a.alias_text) filter(where a.id is not null),'[]'::json) as aliases
        from inventory_item_master m left join inventory_item_aliases a on a.inventory_item_code=m.code group by m.code''')
    plan=plan_mapping([dict(m) for m in cur.fetchall()],sources)
    for item in plan['creations']:
        cur.execute('''insert into inventory_item_master(code,canonical_name,normalized_canonical_name,base_unit,metadata,active)
         values(%s,%s,%s,%s,%s::jsonb,true) on conflict(code) do nothing''',
         (item['code'],item['canonical_name'],normalize_name(item['canonical_name']),item['base_unit'],json.dumps({'source':'SHARED_CALCULATOR','sourceRef':item.get('source')})))
    for item in plan['aliases']:
        # Never steal an existing alias, even if an operator edits the master concurrently.
        cur.execute('''insert into inventory_item_aliases(inventory_item_code,alias_text,normalized_alias)
          values(%s,%s,%s) on conflict(normalized_alias) do nothing returning inventory_item_code''',
          (item['code'],item['alias'],normalize_name(item['alias'])))
        if not cur.fetchone():
            cur.execute('select inventory_item_code from inventory_item_aliases where normalized_alias=%s',(normalize_name(item['alias']),))
            if cur.fetchone()['inventory_item_code'] != item['code']:
                raise ValueError('Alias changed during shared master synchronization')
    return {'created':len(plan['creations']),'aliasesAdded':len(plan['aliases']),'needsReview':plan['unresolved'],
        'scope':'GLOBAL_SHARED_MAJA_CEMPLANG','stockMutation':False,'priceMutation':False,'sourceRows':len(sources)}
