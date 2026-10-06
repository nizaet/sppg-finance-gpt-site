"""Build-time native print smoke test. Synthetic data only, never Drive."""
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lpdh_logic import fallback_lpdh_workbook
from lpdh_approval import render_approval, ASSETS
from pypdf import PdfReader
import base64
from PIL import Image, ImageDraw
from pypdf.generic import ContentStream


def main():
    wb = fallback_lpdh_workbook()
    wb['Identitas']['B7'] = 'SPPG TEST PRINT'
    ws = wb['J_Pengesahan']
    ws['A1'] = 'LEMBAR PENGESAHAN'
    ws['A5'] = '=Identitas!B7'
    ws['E13'] = '=100+5'
    ws.print_area = 'A1:F34'
    for row in range(29,33): ws.row_dimensions[row].height = 18
    for col in ('B','D','F'): ws.column_dimensions[col].width = 30
    out = BytesIO(); wb.save(out)
    assets = {}
    for index,key in enumerate(ASSETS):
        art = Image.new('RGB',(200,80),'white')
        ImageDraw.Draw(art).rectangle((40,20,150,60),fill=(20+index*30,40,100))
        raw=BytesIO(); art.save(raw,format='PNG')
        assets[key]='data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()
    pdf = render_approval(out.getvalue(), assets)
    reader=PdfReader(BytesIO(pdf))
    text = '\n'.join(p.extract_text() or '' for p in reader.pages)
    assert 'SPPG TEST PRINT' in text and '105' in text, 'Native formula print failed'
    drawings=sum(1 for page in reader.pages for operands,operator in ContentStream(page.get_contents(),reader).operations if operator==b'Do')
    assert drawings >= 5, 'Native print omitted approval artwork'
    print('APPROVAL PRINT SELFTEST OK: native workbook formula calculation and PDF output')


if __name__ == '__main__': main()
