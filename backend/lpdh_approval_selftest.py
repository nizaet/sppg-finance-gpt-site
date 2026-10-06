"""Build-time native print smoke test. Synthetic data only, never Drive."""
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lpdh_logic import fallback_lpdh_workbook
from lpdh_approval import render_approval
from pypdf import PdfReader


def main():
    wb = fallback_lpdh_workbook()
    wb['Identitas']['B7'] = 'SPPG TEST PRINT'
    ws = wb['J_Pengesahan']
    ws['A1'] = 'LEMBAR PENGESAHAN'
    ws['A5'] = '=Identitas!B7'
    ws['E13'] = '=100+5'
    ws.print_area = 'A1:F34'
    out = BytesIO(); wb.save(out)
    pdf = render_approval(out.getvalue(), {})
    text = '\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(pdf)).pages)
    assert 'SPPG TEST PRINT' in text and '105' in text, 'Native formula print failed'
    print('APPROVAL PRINT SELFTEST OK: native workbook formula calculation and PDF output')


if __name__ == '__main__': main()
