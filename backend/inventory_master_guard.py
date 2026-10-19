"""Build auditable master/alias changes without modifying quantities or stock."""
from copy import deepcopy
import hashlib
import json


def snapshot_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str).encode()).hexdigest()


def build_master_plan(fields, before, normalize_name, canonical_unit, default_code):
    old=deepcopy(before) if before else None
    code=str(fields.get('code') or (old or {}).get('code') or default_code(str(fields.get('canonical_name') or ''))).upper().strip()
    if not code or len(code)>80 or any(c.isspace() for c in code):
        raise ValueError('Kode master wajib diisi, maksimal 80 karakter, tanpa spasi')
    name=str(fields.get('canonical_name') if fields.get('canonical_name') is not None else (old or {}).get('canonical_name') or '').strip()
    if not name or not normalize_name(name):
        raise ValueError('Nama barang kanonis wajib diisi untuk master baru')
    unit=canonical_unit(fields.get('base_unit')) if 'base_unit' in fields else (old or {}).get('base_unit')
    if not unit and fields.get('require_unit'):
        raise ValueError('Satuan dasar master wajib diisi; jangan mengasumsikan kg/pcs')
    aliases={}
    identity_words=set(normalize_name(name).replace('cabe','cabai').split())
    for alias in [name,*((old or {}).get('aliases') or []),*(fields.get('aliases') or [])]:
        value=str(alias).strip();key=normalize_name(value)
        if not key: raise ValueError('Alias barang tidak boleh kosong')
        alias_words=set(key.replace('cabe','cabai').split())
        if {'cabai','kering'}<=identity_words and 'cabai' in alias_words and 'kering' not in alias_words:
            raise ValueError('Alias cabai kering harus tetap menyebut kering; jangan gabungkan dengan cabai segar')
        aliases.setdefault(key,value)
    proposed={'code':code,'canonical_name':name,'category_code':fields.get('category_code',(old or {}).get('category_code')),
              'base_unit':unit,'aliases':sorted(aliases.values()),
              'metadata':{**((old or {}).get('metadata') or {}),**(fields.get('metadata') or {})},
              'active':bool(fields['active']) if fields.get('active') is not None else bool((old or {}).get('active',True))}
    changed=[key for key in proposed if old is None or proposed[key]!=old.get(key)]
    return {'before':old,'proposed':proposed,'changedFields':changed,'canCommit':bool(changed),'expectedBeforeHash':snapshot_hash(old)}
