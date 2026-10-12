"""Explicit cancellation outbox. BGN files only; never permanently delete."""
import hashlib
from datetime import date
from backend.db import connection
from backend import bgn_drive as drive


def enqueue(cur, site, artifact_key, link, actor):
    if not link:
        return {'status':'SKIPPED','message':'Tidak ada file BGN aktif untuk dipindahkan ke Sampah.'}
    cur.execute('select * from lpdh_bgn_drive_uploads where site=%s and artifact_key=%s and drive_uri=%s',
        (site,artifact_key,link))
    rows=cur.fetchall()
    if len(rows)!=1:
        return {'status':'SKIPPED','message':'File tidak teridentifikasi sebagai upload BGN dokumen ini; file tidak dihapus.'}
    row=rows[0]
    cur.execute('''insert into lpdh_bgn_trash_requests(site,artifact_key,file_id,folder_id,content_hash,service_date,requested_by)
        values(%s,%s,%s,%s,%s,%s,%s) on conflict(site,file_id) do update set updated_at=now() returning id,status''',
        (site,artifact_key,row['file_id'],row['folder_id'],row['content_hash'],row['service_date'],actor))
    request=cur.fetchone()
    return {'requestId':request['id'],'status':request['status']}


def trash_file(api, request):
    site=request['site'];day=date.fromisoformat(str(request['service_date'])[:10])
    files=api.files()
    meta=files.get(fileId=request['file_id'],fields='id,mimeType,trashed,parents,appProperties,capabilities(canTrash)',supportsAllDrives=True).execute()
    marker=hashlib.sha256((site+'|'+request['artifact_key']+'|'+request['content_hash']).encode()).hexdigest()
    if meta.get('mimeType')=='application/vnd.google-apps.folder' or (meta.get('appProperties') or {}).get('sppgArtifact')!=marker:
        raise ValueError('File ownership marker mismatch')
    if meta.get('trashed'):
        return
    if request['folder_id'] not in meta.get('parents',[]) or not (meta.get('capabilities') or {}).get('canTrash'):
        raise ValueError('File moved or trash permission missing')
    folder=files.get(fileId=request['folder_id'],fields='id,name,mimeType,parents,trashed',supportsAllDrives=True).execute()
    if folder.get('trashed') or folder.get('name')!=day.isoformat() or folder.get('mimeType')!='application/vnd.google-apps.folder' or len(folder.get('parents',[]))!=1:
        raise ValueError('Unexpected day folder')
    month=files.get(fileId=folder['parents'][0],fields='name,mimeType,parents,trashed',supportsAllDrives=True).execute()
    if month.get('trashed') or month.get('name')!=day.strftime('%Y-%m') or month.get('mimeType')!='application/vnd.google-apps.folder' or drive.SITES[site][1] not in month.get('parents',[]):
        raise ValueError('Unexpected site root')
    files.update(fileId=request['file_id'],body={'trashed':True},fields='id,trashed',supportsAllDrives=True).execute()
    if not files.get(fileId=request['file_id'],fields='id,trashed',supportsAllDrives=True).execute().get('trashed'):
        raise ValueError('Trash readback failed')


def process(site, request_id):
    with connection() as conn,conn.cursor() as cur:
        cur.execute('select * from lpdh_bgn_trash_requests where id=%s and site=%s for update',(request_id,site))
        request=cur.fetchone()
        if not request:
            raise ValueError('Trash request not found for site')
        if request['status']=='TRASHED':
            return {'requestId':request_id,'status':'TRASHED','message':'File BGN sudah berada di Sampah. Arsip internal tetap disimpan.'}
        status,error='TRASHED',None
        cur.execute('savepoint bgn_trash_attempt')
        try:
            cur.execute('select * from lpdh_bgn_drive_connections where site=%s',(site,))
            saved=cur.fetchone()
            if not saved or saved.get('email')!=drive.SITES[site][0] or saved.get('folder_id')!=drive.SITES[site][1]:
                raise ValueError('Reconnect correct accountant')
            trash_file(drive.service(saved),request)
        except Exception:
            cur.execute('rollback to savepoint bgn_trash_attempt')
            status='FAILED'
            error='Pembatalan tersimpan, tetapi file BGN belum dipindahkan ke Sampah. Periksa koneksi/izin Google dan coba lagi di Koneksi Drive BGN.'
        cur.execute('release savepoint bgn_trash_attempt')
        cur.execute('update lpdh_bgn_trash_requests set status=%s,error_message=%s,updated_at=now() where id=%s',(status,error,request_id))
        conn.commit()
    return {'requestId':request_id,'status':status,'message':error or 'File BGN dipindahkan ke Sampah dan dapat dipulihkan melalui Drive. Arsip internal tetap disimpan.'}


def finish(site, result):
    if not result or not result.get('requestId'):
        return result or {'status':'KEPT','message':'File BGN dan arsip internal tetap disimpan.'}
    try:
        return process(site,result['requestId'])
    except Exception:
        return {**result,'status':'PENDING','message':'Pembatalan tersimpan. Pemindahan file BGN belum terkonfirmasi; coba lagi di Koneksi Drive BGN.'}
