"""Opaque, rotating OAuth refresh sessions, bound to the original client/resource.

Only token hashes are persisted. Families expire absolutely after seven days;
rotation never extends that expiry. A replay revokes its complete token family.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from backend.db import connection, database_ready

SESSION_DAYS = 7


def _hash(token: str) -> str:
    if not token or len(token) > 512:
        raise ValueError('Invalid refresh token')
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _table(cur):
    cur.execute('''create table if not exists sppg_oauth_refresh_tokens (
        token_hash text primary key, family_id uuid not null,
        client_id text not null, resource text not null, audience text not null,
        subject text not null, scope text not null, expires_at timestamptz not null,
        consumed_at timestamptz, revoked_at timestamptz, created_at timestamptz not null default now()
    )''')
    cur.execute('create index if not exists sppg_oauth_refresh_family on sppg_oauth_refresh_tokens(family_id)')


def _insert(cur, token, family, client, resource, audience, subject, scope, expires):
    cur.execute('''insert into sppg_oauth_refresh_tokens(
        token_hash,family_id,client_id,resource,audience,subject,scope,expires_at
    ) values (%s,%s,%s,%s,%s,%s,%s,%s)''',
        (_hash(token),family,client,resource.rstrip('/'),audience,subject,scope,expires))


def create_refresh(client_id, resource, audience, subject, scope) -> str:
    if not database_ready(): raise RuntimeError('Refresh session store unavailable')
    token=secrets.token_urlsafe(48)
    with connection() as conn:
        with conn.cursor() as cur:
            _table(cur)
            _insert(cur,token,uuid.uuid4(),client_id,resource,audience,subject,scope,
                    datetime.now(timezone.utc)+timedelta(days=SESSION_DAYS))
        conn.commit()
    return token


def rotate_refresh(token, client_id, resource, audience, scope, allowed_subjects) -> dict:
    if not database_ready(): raise RuntimeError('Refresh session store unavailable')
    key=_hash(token)
    with connection() as conn:
        with conn.cursor() as cur:
            _table(cur)
            cur.execute('select * from sppg_oauth_refresh_tokens where token_hash=%s for update',(key,))
            row=cur.fetchone()
            if not row or row['client_id']!=client_id or row['resource']!=resource.rstrip('/') or row['audience']!=audience or row['scope']!=scope or row['subject'] not in allowed_subjects:
                raise ValueError('Invalid refresh session binding')
            now=datetime.now(timezone.utc)
            if row.get('consumed_at') or row.get('revoked_at'):
                cur.execute('update sppg_oauth_refresh_tokens set revoked_at=coalesce(revoked_at,now()) where family_id=%s',(row['family_id'],))
                conn.commit()
                raise ValueError('Refresh token replay or revoked session')
            if row['expires_at']<=now: raise ValueError('Refresh session expired')
            new=secrets.token_urlsafe(48)
            cur.execute('update sppg_oauth_refresh_tokens set consumed_at=now() where token_hash=%s and consumed_at is null',(key,))
            _insert(cur,new,row['family_id'],client_id,resource,audience,row['subject'],scope,row['expires_at'])
        conn.commit()
    return {'refresh_token':new,'subject':row['subject'],'scope':scope}
