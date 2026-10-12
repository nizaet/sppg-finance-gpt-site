"""OAuth callback consumes a short-lived, browser-bound, single-use state."""
import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from backend.db import connection
from backend import bgn_drive as drive

router = APIRouter(prefix='/bgn-drive',tags=['lpdh-bgn-drive'])
COOKIE='sppg_bgn_oauth_browser'
COOKIE_PATH='/v1/lpdh/bgn-drive/oauth/callback'


def authorized(request,site):
    if site not in drive.SITES:
        raise HTTPException(422,'Dapur tidak valid.')
    if getattr(request.state,'sppg_role',None) not in ('OWNER',site):
        raise HTTPException(403,'Akun hanya dapat menghubungkan Drive dapur sendiri.')


class SiteIn(BaseModel):
    site:str


class FolderIn(SiteIn):
    folder_id:str=Field(min_length=1,max_length=100)


@router.get('/status')
def status(request:Request,response:Response,site:str):
    authorized(request,site);response.headers['Cache-Control']='no-store'
    ready=drive.configured()
    with connection() as conn,conn.cursor() as cur:
        cur.execute('select email,folder_id,connected_at from lpdh_bgn_drive_connections where site=%s',(site,))
        saved=cur.fetchone()
    return {'site':site,'configured':ready,'expectedEmail':drive.SITES[site][0],
        'expectedFolderId':drive.SITES[site][1],'email':saved['email'] if saved else None,
        'connected':bool(saved),'folderReady':bool(saved and saved['folder_id']==drive.SITES[site][1])}


@router.post('/oauth/start')
def start(payload:SiteIn,request:Request,response:Response):
    authorized(request,payload.site)
    if not drive.configured():raise HTTPException(503,'Konfigurasi koneksi Drive BGN belum lengkap di server.')
    state=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    with connection() as conn,conn.cursor() as cur:
        cur.execute('delete from lpdh_bgn_drive_oauth_states where expires_at<now()')
        cur.execute('insert into lpdh_bgn_drive_oauth_states(state_hash,browser_hash,site,verifier,expires_at) values(%s,%s,%s,%s,%s)',
            (drive.digest(state),drive.digest(browser),payload.site,verifier,datetime.now(timezone.utc)+timedelta(minutes=10)))
        conn.commit()
    response.set_cookie(COOKIE,browser,max_age=600,secure=True,httponly=True,samesite='lax',path=COOKIE_PATH)
    response.headers['Cache-Control']='no-store'
    from urllib.parse import urlencode
    params={'client_id':drive.client()[0],'redirect_uri':drive.CALLBACK,'response_type':'code',
        'scope':'openid email '+drive.DRIVE_SCOPE,'state':state,'access_type':'offline',
        'prompt':'consent select_account','login_hint':drive.SITES[payload.site][0],
        'code_challenge':challenge,'code_challenge_method':'S256'}
    return {'authorizationUrl':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params)}


@router.get('/oauth/callback')
def callback(request:Request):
    # Strip the provider code/state from access logs before returning a response.
    params=dict(request.query_params);request.scope['query_string']=b''
    state=params.get('state','');browser=request.cookies.get(COOKIE,'');message='Koneksi gagal. Kembali ke LPDH dan hubungkan ulang.'
    if state and browser:
        try:
            with connection() as conn,conn.cursor() as cur:
                cur.execute('''delete from lpdh_bgn_drive_oauth_states where state_hash=%s and browser_hash=%s
                    and expires_at>now() returning site,verifier''',(drive.digest(state),drive.digest(browser)))
                saved=cur.fetchone();conn.commit()
            if saved and not params.get('error') and params.get('code'):
                tokens=drive.exchange(params['code'],saved['verifier'])
                email=drive.validate_identity(saved['site'],tokens)
                ciphertext=drive.cipher().encrypt(json.dumps({'refresh_token':tokens['refresh_token'],'scope':tokens['scope']}).encode()).decode()
                with connection() as conn,conn.cursor() as cur:
                    cur.execute('''insert into lpdh_bgn_drive_connections(site,email,token_ciphertext) values(%s,%s,%s)
                        on conflict(site) do update set email=excluded.email,token_ciphertext=excluded.token_ciphertext,
                        folder_id=null,updated_at=now()''',(saved['site'],email,ciphertext));conn.commit()
                message='Akun Google tersambung. Kembali ke LPDH, klik Periksa Koneksi, lalu Pilih Folder BGN.'
        except Exception:
            # Never expose Google errors, authorization codes or tokens.
            message='Koneksi gagal. Pastikan memakai email akuntan sesuai dapur dan memberikan izin Drive. Hubungkan ulang dari LPDH.'
    result=HTMLResponse('<!doctype html><html lang="id"><head><meta charset="utf-8"><title>Koneksi Drive BGN</title></head><body><h2>Drive BGN</h2><p>'+message+'</p><p>Anda boleh menutup tab ini.</p></body></html>',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"})
    result.delete_cookie(COOKIE,path=COOKIE_PATH,secure=True,httponly=True,samesite='lax')
    return result


@router.post('/picker')
def picker(payload:SiteIn,request:Request,response:Response):
    authorized(request,payload.site);response.headers['Cache-Control']='no-store'
    with connection() as conn,conn.cursor() as cur:
        cur.execute('select * from lpdh_bgn_drive_connections where site=%s',(payload.site,));saved=cur.fetchone()
    if not saved:raise HTTPException(409,'Hubungkan akun Google dapur terlebih dahulu.')
    try:
        token=drive.access_token(saved)
        client_id=drive.client()[0]
        return {'accessToken':token,'apiKey':os.getenv('SPPG_BGN_DRIVE_PICKER_API_KEY','').strip(),
            'appId':client_id.split('-')[0],'expectedFolderId':drive.SITES[payload.site][1]}
    except Exception as exc:
        raise HTTPException(502,'Koneksi Google kedaluwarsa atau dicabut. Hubungkan ulang.') from exc


@router.post('/folder')
def folder(payload:FolderIn,request:Request):
    authorized(request,payload.site)
    if payload.folder_id!=drive.SITES[payload.site][1]:raise HTTPException(422,'Folder tidak sesuai dapur. Pilih folder BGN yang ditetapkan.')
    with connection() as conn,conn.cursor() as cur:
        cur.execute('select * from lpdh_bgn_drive_connections where site=%s for update',(payload.site,));saved=cur.fetchone()
        if not saved:raise HTTPException(409,'Hubungkan akun Google terlebih dahulu.')
        try:drive.validate_folder(drive.service(saved),payload.site,payload.folder_id)
        except Exception as exc:raise HTTPException(403,'Izin upload folder BGN belum tersedia. Pilih melalui Google Picker dan periksa akses akun.') from exc
        cur.execute('update lpdh_bgn_drive_connections set folder_id=%s,updated_at=now() where site=%s',(payload.folder_id,payload.site));conn.commit()
    return {'saved':True,'folderReady':True}


@router.post('/disconnect')
def disconnect(payload:SiteIn,request:Request):
    authorized(request,payload.site)
    with connection() as conn,conn.cursor() as cur:
        cur.execute('delete from lpdh_bgn_drive_connections where site=%s',(payload.site,))
        cur.execute('delete from lpdh_bgn_drive_oauth_states where site=%s',(payload.site,));conn.commit()
    return {'disconnected':True}

