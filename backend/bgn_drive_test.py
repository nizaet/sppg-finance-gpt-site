"""Deterministic, explicitly non-financial PDF for verifying BGN upload."""
import hashlib
from datetime import date
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from backend import bgn_drive as drive


def test_pdf(site, service_date):
    if site not in drive.SITES:
        raise ValueError('Dapur tidak valid.')
    day=date.fromisoformat(str(service_date)[:10])
    output=BytesIO()
    pdf=canvas.Canvas(output,pagesize=A4,invariant=1)
    pdf.setTitle('UJI KONEKSI - BUKAN BUKTI TRANSAKSI')
    pdf.setAuthor('SPPG - Tes Koneksi Drive BGN')
    pdf.setFillColorRGB(.65,.10,.10)
    pdf.setFont('Helvetica-Bold',21)
    pdf.drawString(48,770,'UJI KONEKSI DRIVE BGN')
    pdf.setFont('Helvetica-Bold',16)
    pdf.drawString(48,737,'BUKAN BUKTI TRANSAKSI')
    pdf.setFillColorRGB(.1,.1,.1)
    pdf.setFont('Helvetica',12)
    for y,text in [(690,'Dapur: '+site),(665,'Tanggal HPE: '+day.isoformat()),
        (615,'File ini hanya untuk menguji upload dan pembacaan kembali.'),
        (590,'Tidak membuat invoice, kuitansi, transfer, atau antrean Maker.'),
        (565,'Tidak mengubah saldo maupun data harian LPDH.'),
        (515,'Tujuan: folder BGN dapur / '+day.strftime('%Y-%m')+' / '+day.isoformat()),
        (465,'Tes yang diulang memakai kembali file uji yang sama jika tersedia.')]:
        pdf.drawString(48,y,text)
    pdf.setFont('Helvetica-Bold',12)
    pdf.setFillColorRGB(.65,.10,.10)
    pdf.drawString(48,400,'JANGAN DIGUNAKAN SEBAGAI BUKTI PEMBAYARAN.')
    pdf.showPage();pdf.save()
    return output.getvalue()


def verified_test_upload(cur,site,service_date):
    day=date.fromisoformat(str(service_date)[:10])
    content=test_pdf(site,day)
    key=f'bgn-connection-test-{site}-{day}'
    filename=f'UJI_KONEKSI_BUKAN_BUKTI_TRANSAKSI_{site}_{day}.pdf'
    drive.upload(cur,site,day,key,filename,content,'application/pdf')
    cur.execute('select * from lpdh_bgn_drive_uploads where site=%s and artifact_key=%s and content_hash=%s',
        (site,key,hashlib.sha256(content).hexdigest()))
    record=cur.fetchone()
    if not record:raise ValueError('Catatan upload belum tersedia untuk verifikasi.')
    cur.execute('select * from lpdh_bgn_drive_connections where site=%s',(site,))
    saved=cur.fetchone()
    if not saved or saved['email']!=drive.SITES[site][0]:raise ValueError('Koneksi akun berubah sebelum verifikasi.')
    # Google reports size and MD5 for the uploaded binary; verify both and its
    # actual parent before reporting success. Never trust only a returned link.
    metadata=drive.service(saved).files().get(fileId=record['file_id'],
        fields='id,name,mimeType,trashed,parents,size,md5Checksum,webViewLink',supportsAllDrives=True).execute()
    if metadata.get('trashed') or metadata.get('mimeType')!='application/pdf' or record['folder_id'] not in metadata.get('parents',[]) or int(metadata.get('size') or 0)!=len(content) or metadata.get('md5Checksum')!=hashlib.md5(content).hexdigest():
        raise ValueError('Upload belum lolos pemeriksaan file Drive.')
    link=metadata.get('webViewLink') or record['drive_uri']
    if not str(link).startswith('https://drive.google.com/'):
        raise ValueError('Link hasil verifikasi tidak valid.')
    return {'verified':True,'driveUri':link,'filename':metadata.get('name') or filename,
        'drivePath':day.strftime('%Y-%m')+'/'+day.isoformat(),'site':site,'serviceDate':day.isoformat()}

