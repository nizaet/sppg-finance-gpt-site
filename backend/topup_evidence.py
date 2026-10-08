"""Validate actual file bytes before archiving user-provided TopUp proof."""
import base64
from io import BytesIO

MAX_BYTES=5*1024*1024


def decode_evidence(encoded):
    try:
        content=base64.b64decode(encoded,validate=True)
    except Exception as exc:
        raise ValueError('Isi berkas tidak valid.') from exc
    if not content or len(content)>MAX_BYTES:
        raise ValueError('Bukti maksimal 5 MB per berkas.')
    if content.startswith(b'%PDF-'):
        from pypdf import PdfReader
        try:
            pdf=PdfReader(BytesIO(content))
            if pdf.is_encrypted or not 1<=len(pdf.pages)<=200:
                raise ValueError('PDF harus dapat dibuka, tanpa password, maksimal 200 halaman.')
        except Exception as exc:
            raise ValueError('PDF tidak dapat dibaca atau dilindungi password.') from exc
        return content,'application/pdf','pdf'
    from PIL import Image
    try:
        with Image.open(BytesIO(content)) as picture:
            kind=picture.format
            if kind not in ('JPEG','PNG') or picture.width*picture.height>40000000:
                raise ValueError('Gunakan JPEG/PNG maksimal 40 megapiksel.')
            picture.verify()
    except Exception as exc:
        raise ValueError('Berkas harus JPEG/PNG atau PDF yang valid.') from exc
    return content,('image/jpeg' if kind=='JPEG' else 'image/png'),('jpg' if kind=='JPEG' else 'png')

