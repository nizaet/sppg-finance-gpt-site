"""Print the official J sheet, preserving its source formulas and layout.

Only a disposable print copy is saved through openpyxl. Downloaded workbooks
continue to use lpdh_template's lossless, input-only package patching.
"""
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from pypdf import PdfReader

ASSETS = {
    'approvalFinanceSignature': ('B29', 130, 42),
    'approvalSppgSignature': ('D29', 130, 42),
    'approvalFoundationSignature': ('F29', 130, 42),
    'approvalSppgStamp': ('D31', 65, 30),
    'approvalFoundationStamp': ('F31', 65, 30),
}


def incentive_defaults(daily, calculated, service_date, site, receipt=None):
    out = copy.deepcopy(daily)
    if out.get('_historicalGeneratedSnapshot'):
        return out
    inc = out.setdefault('incentive', {})
    automatic = set(inc.get('_automaticAmounts') or [])
    for field in ('statementAmount', 'paidAmount'):
        if inc.get(field) in (None, '') or field in automatic:
            inc[field] = calculated
            automatic.add(field)
    inc['_automaticAmounts'] = sorted(automatic)
    for field, value in {
        'paymentDate': service_date, 'receiptSigned': 'Ya',
        'proofNo': f'BYR-INS-{site}-{service_date.replace("-", "")}',
        'receiptNo': receipt,
    }.items():
        if inc.get(field) in (None, '') and value is not None:
            inc[field] = value
    return out


def approval_hash(masters, daily, service_date, preview):
    # The assigned Drive link and approval audit are outputs, not print inputs.
    data = copy.deepcopy(daily)
    data.pop('_approval', None)
    data.pop('_approvalHistory', None)
    inc = data.setdefault('incentive', {})
    inc.pop('evidenceLink', None)
    inc.pop('approvalEvidenceLink', None)
    material = {'date': service_date, 'daily': data,
                'template': masters.get('_officialTemplateBase64'),
                'signers': masters.get('signers'), 'assets': masters.get('assets'),
                'identity': masters.get('identity'), 'parameters': masters.get('parameters'),
                'summary': {k: preview.get(k) for k in ('rawTotal', 'operationalTotal', 'incentiveCalculated', 'production', 'balance', 'topup')}}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


def attach_approval(daily, archive, digest, actor, timestamp):
    out = copy.deepcopy(daily)
    link = str(archive.get('driveUri') or '')
    if not link.startswith('https://'):
        raise ValueError('Drive tidak mengembalikan link PDF pengesahan yang valid.')
    previous = out.get('_approval')
    if previous and previous.get('hash') != digest:
        out.setdefault('_approvalHistory', []).append(previous)
    out['_approval'] = {'status': 'FINAL', 'hash': digest, 'pdfLink': link,
                        'folderId': archive.get('folderId'), 'finalizedBy': actor,
                        'finalizedAt': timestamp, 'evidenceType': 'PENGESAHAN'}
    inc = out.setdefault('incentive', {})
    inc['approvalEvidenceLink'] = link
    # Preserve a separately entered real payment-evidence link.
    old_auto = (previous or {}).get('pdfLink')
    if not inc.get('evidenceLink') or inc.get('evidenceLink') == old_auto:
        inc['evidenceLink'] = link
    return out


def print_copy(content, assets):
    """Hide other sheets only in the print copy; references remain available."""
    from backend.generated_document_settings import validate_artwork
    wb = load_workbook(BytesIO(content), keep_links=False)
    # Never evaluate network/DDE formulas supplied in an uploaded workbook.
    import re
    for sheet in wb:
        for row in sheet:
            for cell in row:
                if cell.data_type == 'f' and re.search(r'WEBSERVICE\s*\(|RTD\s*\(|DDE\s*\(|\[[0-9]+\]|https?://', str(cell.value), re.I):
                    raise ValueError('Template cetak tidak boleh memakai rumus sumber eksternal.')
    if 'J_Pengesahan' not in wb.sheetnames:
        raise ValueError('Template tidak memiliki sheet J_Pengesahan.')
    ws = wb['J_Pengesahan']
    for sheet in wb:
        sheet.sheet_state = 'visible' if sheet == ws else 'hidden'
    wb.active = wb.index(ws)
    ws.sheet_view.tabSelected = True
    # Preserve an explicit official print area. Legacy official templates omit it.
    if not ws.print_area:
        ws.print_area = 'A1:F34'
    for key, (anchor, width, height) in ASSETS.items():
        if not assets.get(key):
            continue
        raw, _ = validate_artwork(str(assets[key]).split(',', 1)[-1])
        image = Image(BytesIO(raw))
        factor = min(width / image.width, height / image.height)
        image.width *= factor
        image.height *= factor
        ws.add_image(image, anchor)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def render_approval(content, assets):
    binary = shutil.which('libreoffice') or shutil.which('soffice')
    if not binary:
        raise ValueError('Mesin cetak template belum tersedia. Dokumen tidak difinalkan.')
    with tempfile.TemporaryDirectory(prefix='lpdh-approval-') as folder:
        root = Path(folder)
        source = root / 'J_Pengesahan.xlsx'
        source.write_bytes(print_copy(content, assets))
        # Independent profiles avoid concurrent print jobs sharing state.
        profile = (root / 'profile').as_uri()
        subprocess.run([binary, f'-env:UserInstallation={profile}', '--headless',
                        '--convert-to', 'pdf:calc_pdf_Export', '--outdir', str(root), str(source)],
                       check=True, timeout=60, capture_output=True)
        target = root / 'J_Pengesahan.pdf'
        if not target.exists():
            raise ValueError('PDF J_Pengesahan belum berhasil dibuat.')
        data = target.read_bytes()
        reader = PdfReader(BytesIO(data))
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        if not reader.pages or 'PENGESAHAN' not in text.upper() or '#REF!' in text:
            raise ValueError('Hasil cetak template tidak valid. Periksa template resmi.')
        return data
