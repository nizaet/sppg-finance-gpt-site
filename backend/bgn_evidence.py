"""BGN evidence is distinct from internal Maker archives; never mutate money."""
import hashlib
from backend import bgn_drive as drive


def upload_verified(cur, site, service_date, key, filename, content, mime_type):
    drive.upload(cur, site, service_date, key, filename, content, mime_type)
    cur.execute('select * from lpdh_bgn_drive_uploads where site=%s and artifact_key=%s and content_hash=%s',
        (site, key, hashlib.sha256(content).hexdigest()))
    record = cur.fetchone()
    if not record:
        raise ValueError('BGN upload record missing')
    cur.execute('select * from lpdh_bgn_drive_connections where site=%s', (site,))
    saved = cur.fetchone()
    if not saved or saved.get('email') != drive.SITES[site][0] or saved.get('folder_id') != drive.SITES[site][1]:
        raise ValueError('BGN connection changed')
    meta = drive.service(saved).files().get(fileId=record['file_id'],
        fields='id,mimeType,trashed,parents,size,md5Checksum,webViewLink', supportsAllDrives=True).execute()
    if (meta.get('trashed') or meta.get('mimeType') != mime_type
            or record['folder_id'] not in meta.get('parents', [])
            or int(meta.get('size') or 0) != len(content)
            or meta.get('md5Checksum') != hashlib.md5(content).hexdigest()):
        raise ValueError('BGN metadata verification failed')
    link = meta.get('webViewLink') or record['drive_uri']
    if not str(link).startswith('https://drive.google.com/'):
        raise ValueError('BGN link invalid')
    return link
