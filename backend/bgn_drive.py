"""Per-kitchen BGN OAuth and upload transport, isolated from internal Drive."""
import base64
import hashlib
import json
import os
from datetime import date
from io import BytesIO
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SITES = {
    'MAJA': ('nakamotoy306@gmail.com', '15-XbfpHjrf_PVTnSw12o7XUBrQcGeNaU'),
    'CEMPLANG': ('lidiyamaulidiya2020@gmail.com', '15qKQFAP4UqPU-o3hmc50SW5tDRkZC9qF'),
}
ORIGIN = 'https://sppg-finance-gpt-site-production-5b7d.up.railway.app'
CALLBACK = ORIGIN + '/v1/lpdh/bgn-drive/oauth/callback'
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cipher():
    from cryptography.fernet import Fernet
    key = os.getenv('SPPG_BGN_DRIVE_TOKEN_KEY', '').strip()
    if not key:
        raise ValueError('Kunci enkripsi Drive BGN belum diatur di server.')
    return Fernet(key.encode())


def client():
    # Reuse only OAuth client identity; never the internal account refresh token.
    from backend.google_services import _drive_oauth_info
    info = _drive_oauth_info()
    if not info.get('client_id') or not info.get('client_secret'):
        raise ValueError('Client OAuth server belum lengkap.')
    return info['client_id'], info['client_secret']


def configured():
    try:
        client(); cipher()
        return bool(os.getenv('SPPG_BGN_DRIVE_PICKER_API_KEY', '').strip())
    except Exception:
        return False


def json_request(url, fields=None, access_token=None):
    body = urlencode(fields).encode() if fields is not None else None
    headers = {'Content-Type':'application/x-www-form-urlencoded'} if body is not None else {}
    if access_token:
        headers['Authorization'] = 'Bearer ' + access_token
    # Fixed Google endpoints only; provider error bodies/tokens never logged.
    with urlopen(Request(url, data=body, headers=headers), timeout=25) as response:
        return json.load(response)


def exchange(code, verifier):
    client_id, secret = client()
    return json_request('https://oauth2.googleapis.com/token', {
        'code':code, 'code_verifier':verifier, 'client_id':client_id,
        'client_secret':secret, 'redirect_uri':CALLBACK, 'grant_type':'authorization_code'})


def validate_identity(site, tokens):
    if DRIVE_SCOPE not in str(tokens.get('scope') or '').split():
        raise ValueError('Izin upload Drive belum diberikan.')
    identity = json_request('https://openidconnect.googleapis.com/v1/userinfo', access_token=tokens['access_token'])
    if identity.get('email_verified') is not True or str(identity.get('email') or '').lower() != SITES[site][0]:
        raise ValueError('Akun Google tidak sesuai dapur.')
    if not tokens.get('refresh_token'):
        raise ValueError('Izin akses berkelanjutan belum diberikan. Hubungkan ulang.')
    return identity['email'].lower()


def access_token(connection):
    stored = json.loads(cipher().decrypt(connection['token_ciphertext'].encode()))
    client_id, secret = client()
    result = json_request('https://oauth2.googleapis.com/token', {
        'client_id':client_id, 'client_secret':secret, 'refresh_token':stored['refresh_token'],
        'grant_type':'refresh_token'})
    if DRIVE_SCOPE not in str(result.get('scope') or stored.get('scope') or '').split():
        raise ValueError('Izin Drive BGN sudah dicabut.')
    return result['access_token']


def service(connection):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    credentials = Credentials(token=access_token(connection))
    return build('drive','v3',http=AuthorizedHttp(credentials,http=httplib2.Http(timeout=30)),cache_discovery=False)


def validate_folder(api, site, folder_id):
    if folder_id != SITES[site][1]:
        raise ValueError('Pilih folder BGN yang ditetapkan untuk dapur ini.')
    folder = api.files().get(fileId=folder_id, fields='id,mimeType,trashed,capabilities(canAddChildren)',supportsAllDrives=True).execute()
    if folder.get('trashed') or folder.get('mimeType') != 'application/vnd.google-apps.folder' or not (folder.get('capabilities') or {}).get('canAddChildren'):
        raise ValueError('Akun tidak memiliki izin upload ke folder BGN.')
    return folder


def upload(cur, site, service_date, artifact_key, filename, content, mime_type):
    day = date.fromisoformat(str(service_date)[:10])
    cur.execute('select * from lpdh_bgn_drive_connections where site=%s', (site,))
    connection = cur.fetchone()
    if not connection or connection.get('email') != SITES[site][0] or connection.get('folder_id') != SITES[site][1]:
        raise ValueError('Hubungkan akun akuntan dan pilih folder BGN terlebih dahulu.')
    api = service(connection)
    validate_folder(api,site,connection['folder_id'])
    content_hash = hashlib.sha256(content).hexdigest()
    cur.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))',('bgn-drive:'+site,))
    cur.execute('select * from lpdh_bgn_drive_uploads where site=%s and artifact_key=%s and content_hash=%s',(site,artifact_key,content_hash))
    previous = cur.fetchone()
    if previous:
        live = api.files().get(fileId=previous['file_id'],fields='id,trashed,parents',supportsAllDrives=True).execute()
        if not live.get('trashed') and previous['folder_id'] in live.get('parents',[]):
            return previous['drive_uri']
    folder_id = connection['folder_id']
    for name in (day.strftime('%Y-%m'),day.isoformat()):
        query = "'%s' in parents and name='%s' and mimeType='application/vnd.google-apps.folder' and trashed=false" % (folder_id,name)
        found = api.files().list(q=query,fields='files(id)',supportsAllDrives=True,includeItemsFromAllDrives=True,pageSize=100).execute().get('files',[])
        if len(found)>1:
            raise ValueError('Folder BGN bulan/tanggal duplikat; periksa folder sebelum upload.')
        folder_id = found[0]['id'] if found else api.files().create(body={'name':name,'mimeType':'application/vnd.google-apps.folder','parents':[folder_id]},fields='id',supportsAllDrives=True).execute()['id']
    # Idempotence survives a Drive success followed by a DB rollback.
    marker = hashlib.sha256((site+'|'+artifact_key+'|'+content_hash).encode()).hexdigest()
    found = api.files().list(q="'%s' in parents and trashed=false and appProperties has { key='sppgArtifact' and value='%s' }" % (folder_id,marker),fields='files(id,webViewLink)',supportsAllDrives=True,includeItemsFromAllDrives=True,pageSize=100).execute().get('files',[])
    if len(found)>1:
        raise ValueError('Bukti BGN duplikat; periksa folder sebelum mencoba ulang.')
    if found:
        file = found[0]
    else:
        from googleapiclient.http import MediaIoBaseUpload
        file = api.files().create(body={'name':filename,'parents':[folder_id],'appProperties':{'sppgArtifact':marker}},media_body=MediaIoBaseUpload(BytesIO(content),mimetype=mime_type,resumable=False),fields='id,webViewLink',supportsAllDrives=True).execute()
    uri = file.get('webViewLink') or 'https://drive.google.com/file/d/'+file['id']+'/view'
    cur.execute('''insert into lpdh_bgn_drive_uploads(site,artifact_key,content_hash,file_id,folder_id,drive_uri,service_date)
        values(%s,%s,%s,%s,%s,%s,%s) on conflict(site,artifact_key,content_hash) do update
        set file_id=excluded.file_id,folder_id=excluded.folder_id,drive_uri=excluded.drive_uri,uploaded_at=now()''',
        (site,artifact_key,content_hash,file['id'],folder_id,uri,day))
    return uri

