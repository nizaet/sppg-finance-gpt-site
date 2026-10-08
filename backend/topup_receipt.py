"""Banper receipt snapshots: incoming funds evidence, never an expense/maker invoice."""
import base64
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from fastapi import HTTPException
from backend.generated_document_settings import checked_number, validate_artwork

MONEY_FIELDS=('rawAmount','operationalAmount','incentiveAmount')
TEXT_FIELDS=('sppgName','foundation','headName','foundationName','address','payer','purpose')
IMAGE_FIELDS=('letterhead','headSignature','headStamp','foundationSignature','foundationStamp')

def allocate_total(value):
    total=financial({'date':'2000-01-01','rawAmount':value})['rawAmount']
    raw=(total*67+50)//100
    incentive=(total*13+50)//100
    return {'rawAmount':raw,'operationalAmount':total-raw-incentive,'incentiveAmount':incentive}

def financial(row):
    amounts=[]
    for key in MONEY_FIELDS:
        try: value=Decimal(str(row.get(key) or 0))
        except InvalidOperation: raise ValueError('Nominal TopUp tidak valid.')
        if not value.is_finite() or value<0 or value>=Decimal('1000000000000000') or value!=value.to_integral_value():
            raise ValueError('Nominal TopUp harus rupiah bulat, tidak negatif, dan dalam batas nilai.')
        amounts.append(int(value))
    return {'date':date.fromisoformat(str(row.get('date') or '')).isoformat(),
            'reference':str(row.get('reference') or '').strip(), **dict(zip(MONEY_FIELDS,amounts))}

def defaults(masters):
    identity=masters.get('identity') or {}; signers=masters.get('signers') or []; assets=masters.get('assets') or {}
    return {'sppgName':identity.get('sppgName') or '', 'foundation':identity.get('foundation') or '',
        'headName':(signers[1].get('name') if len(signers)>1 else '') or '',
        'foundationName':(signers[2].get('name') if len(signers)>2 else '') or '',
        'address':identity.get('city') or '', 'payer':'Kuasa Pengguna Anggaran Badan Gizi Nasional.',
        'purpose':'Dana Bantuan Pemerintah untuk kegiatan Program Makan Bergizi Gratis',
        'headSignature':assets.get('approvalSppgSignature') or '', 'headStamp':assets.get('approvalSppgStamp') or '',
        'foundationSignature':assets.get('approvalFoundationSignature') or '', 'foundationStamp':assets.get('approvalFoundationStamp') or '',
        'letterhead':''}

def validate_profile(profile):
    result={key:str(profile.get(key) or '').strip() for key in TEXT_FIELDS+IMAGE_FIELDS}
    for key in TEXT_FIELDS:
        if len(result[key])>600: raise ValueError('Isian identitas maksimal 600 karakter.')
    for key in ('sppgName','foundation','headName','foundationName','payer','purpose'):
        if not result[key]: raise ValueError('Lengkapi nama SPPG, Yayasan, kedua pengesah, sumber dana, dan uraian.')
    for key in IMAGE_FIELDS:
        if result[key]: validate_artwork(result[key].split(',',1)[-1])
    return result

def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def attach(data,receipt,link):
    rows=data.get('topups') or []
    row=next((r for r in rows if r.get('_topupReceiptId')==receipt['id']),None)
    expected=receipt['snapshot']['funds'] if receipt['status']=='FINAL' else receipt['snapshot'].get('sourceFunds',receipt['snapshot']['funds'])
    if row is None or financial(row) not in (expected,receipt['snapshot']['funds']):
        raise HTTPException(409,'Baris TopUp berubah. Simpan dan buat ulang draft kuitansi sebelum finalisasi.')
    if link:
        row.update(receipt['snapshot']['funds'])
    row['receiptNo']=receipt['document_number']; row['evidenceLink']=link
    data['_reviewValidated']=False
    return data

def protect_final_rows(cur,site,service_date,data):
    cur.execute("select id,document_number,snapshot,pdf_link from lpdh_topup_receipts where site=%s and service_date=%s and status='FINAL'",(site,service_date))
    for receipt in cur.fetchall():
        rows=data.get('topups') or []
        matches=[r for r in rows if str(r.get('_topupReceiptId'))==str(receipt['id'])]
        if not matches:
            # Recover only an unambiguous server-issued receipt identity, not by amount.
            matches=[r for r in rows if not r.get('_topupReceiptId') and r.get('receiptNo')==receipt['document_number'] and r.get('evidenceLink')==receipt['pdf_link']]
        row=matches[0] if len(matches)==1 else None
        expected=financial(receipt['snapshot']['funds'])
        actual=financial(row) if row is not None else None
        locked_fields=('date',)+MONEY_FIELDS
        if actual is None or any(actual[k]!=expected[k] for k in locked_fields):
            raise HTTPException(409,'TopUp memiliki kuitansi FINAL. Batalkan kuitansi sebelum mengubah atau menghapus penerimaannya.')
        row['_topupReceiptId']=receipt['id']
        row['receiptNo']=receipt['document_number'];row['evidenceLink']=receipt['pdf_link']

def words(n):
    n=int(n); small=['nol','satu','dua','tiga','empat','lima','enam','tujuh','delapan','sembilan','sepuluh','sebelas']
    if n<12:return small[n]
    if n<20:return words(n-10)+' belas'
    if n<100:return words(n//10)+' puluh'+(' '+words(n%10) if n%10 else '')
    if n<200:return 'seratus'+(' '+words(n-100) if n>100 else '')
    if n<1000:return words(n//100)+' ratus'+(' '+words(n%100) if n%100 else '')
    if n<2000:return 'seribu'+(' '+words(n-1000) if n>1000 else '')
    for value,label in ((10**12,'triliun'),(10**9,'miliar'),(10**6,'juta'),(1000,'ribu')):
        if n>=value:return words(n//value)+' '+label+(' '+words(n%value) if n%value else '')

def render_receipt(receipt,final=False):
    from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Spacer,KeepTogether,Flowable,Image,HRFlowable
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.utils import ImageReader
    from backend.generated_document_pdf import date_label
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from xml.sax.saxutils import escape
    def p(value,bold=False,align=0,size=12):
        text=escape(str(value or '')).replace('\n','<br/>')
        return Paragraph(text,ParagraphStyle('banper',fontName='Times-Bold' if bold else 'Times-Roman',fontSize=size,leading=size+3,alignment=align))
    profile=receipt['snapshot']['profile']; funds=receipt['snapshot']['funds']; total=sum(funds[k] for k in MONEY_FIELDS)
    output=BytesIO(); width=A4[0]-90
    story=[]
    kop_text=[p(profile['sppgName'].upper(),True,TA_CENTER,12),p(profile['foundation'].upper(),True,TA_CENTER,12),p(profile.get('address'),align=TA_CENTER,size=10)]
    if profile.get('letterhead'):
        raw=base64.b64decode(profile['letterhead'].split(',',1)[-1]);iw,ih=ImageReader(BytesIO(raw)).getSize()
        if iw>=3*ih:
            w=min(width,100*iw/ih);story += [Image(BytesIO(raw),width=w,height=w*ih/iw),Spacer(1,18)]
        else:
            w=min(76,76*iw/ih)
            kop=Table([[Image(BytesIO(raw),width=w,height=w*ih/iw),kop_text,'']],colWidths=[86,width-172,86])
            kop.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
            story += [kop,Spacer(1,12)]
    else:
        story += kop_text+[Spacer(1,12)]
    story += [HRFlowable(width='100%',thickness=1),Spacer(1,22),p('KWITANSI',True,TA_CENTER,14),p('No. '+receipt['document_number'],align=TA_CENTER,size=10),Spacer(1,26)]
    details=Table([
        [p('Sudah terima dari',True,size=11),p(':',size=11),p(profile['payer'],size=11)],
        [p('Uang sebanyak',True,size=11),p(':',size=11),p('Rp '+f'{total:,}'.replace(',','.'),True,size=12)],
        [p('Terbilang',True,size=11),p(':',size=11),p(words(total).capitalize()+' rupiah',size=11)],
        [p('Untuk pembayaran',True,size=11),p(':',size=11),p(profile['purpose']+' di '+profile['sppgName']+', tanggal '+date_label(funds['date']),size=11)],
    ],colWidths=[112,12,width-124])
    details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
    story += [details,Spacer(1,32)]
    class Signing(Flowable):
        def __init__(self,prefix):self.prefix=prefix;self.width=width/2;self.height=104
        def draw(self):
            center=self.width/2
            for field,x,y,w,h in ((self.prefix+'Stamp',center-62,12,82,82),(self.prefix+'Signature',center-38,26,112,58)):
                if profile.get(field):self.canv.drawImage(ImageReader(BytesIO(base64.b64decode(profile[field].split(',',1)[-1]))),x,y,w,h,mask='auto',preserveAspectRatio=True,anchor='c')
    signatures=Table([[p('Kepala SPPG\n'+profile['sppgName'],align=TA_CENTER,size=11),p('Yang Menerima\nPenerima Bantuan',align=TA_CENTER,size=11)],
        [Signing('head'),Signing('foundation')],
        [p(profile['headName'],True,TA_CENTER,11),p(profile['foundationName'],True,TA_CENTER,11)],
        ['',p(profile['foundation'],align=TA_CENTER,size=10)]],colWidths=[width/2,width/2])
    signatures.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story += [KeepTogether(signatures)]
    def page(canvas,doc):
        if not final:
            canvas.saveState();canvas.setFillColorRGB(.87,.87,.87);canvas.setFont('Helvetica-Bold',48);canvas.translate(A4[0]/2,A4[1]/2);canvas.rotate(35);canvas.drawCentredString(0,0,'DRAFT');canvas.restoreState()
    SimpleDocTemplate(output,pagesize=A4,leftMargin=45,rightMargin=45,topMargin=42,bottomMargin=42,title=receipt['document_number']).build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()

