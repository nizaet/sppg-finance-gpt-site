"""Printable PDFs using the Maja invoice identities and supplied artwork."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    from .generated_document_logic import receipt_number
except ImportError:
    from generated_document_logic import receipt_number

ASSETS = Path(__file__).with_name("document_assets")
MONTHS = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]


def money(value):
    return "Rp " + f"{float(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def date_label(value):
    value = date.fromisoformat(str(value)[:10])
    return f"{value.day:02d} {MONTHS[value.month]} {value.year}"


def p(value, bold=False, align=0, size=8):
    text = escape(str(value or "")).replace("\n", "<br/>")
    if bold:
        text = f"<b>{text}</b>"
    return Paragraph(text, ParagraphStyle("doc", fontName="Helvetica", fontSize=size, leading=size + 3, alignment=align))


def image(name, width, height):
    path = ASSETS / name
    return Image(str(path), width=width, height=height, kind="proportional") if path.exists() else Spacer(width, height)


def asset_profile(document):
    profile = (document.get("header") or {}).get("assetProfile")
    return profile if document.get("site") == "MAJA" and profile in {"maja-koperasi", "maja-yayasan"} else ""


def header(document, title, number=None, width=523):
    h = document["header"]
    profile = asset_profile(document)
    logo = image("maja-koperasi-0.png" if profile == "maja-koperasi" else "maja-yayasan-1.png", 48, 48) if profile else Spacer(48, 48)
    company = [p(h.get("issuerName"), True, size=9), p(h.get("issuerSubtitle")), p(h.get("issuerAddress"))]
    meta = [p(title, True, size=11), p(f"Nomor: {number or document['documentNumber']}"), p(f"Tanggal: {date_label(document['serviceDate'])}"), p(document["status"], True)]
    table = Table([[logo, company, meta]], colWidths=[58, width - 250, 192])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    return table


def signatures(document, recipient=None, width=523):
    h = document["header"]
    sender_name = h.get("senderSignatory") or ""
    # Do not distribute personal signature/stamp images in the public repo.
    # Operator signs the printed final PDF and attaches the signed evidence.
    sender = Spacer(140, 55)
    receiver_name = recipient if recipient is not None else h.get("recipientSignatory") or "________________"
    # Individual recipients sign after printing. Do not reuse another person's signature.
    receiver = Spacer(125, 55)
    result = Table([
        [p("Metode Pembayaran", True), p("Penerima", align=TA_CENTER), p("Hormat Kami", align=TA_CENTER)],
        [[p(h.get("paymentMethod") or "Transfer"), p("Bank: " + str(h.get("bankName") or "")),
          p("Nomor Rekening: " + str(h.get("accountNumber") or "")), p("Atas Nama: " + str(h.get("accountName") or ""))], receiver, sender],
        ["", p(receiver_name, align=TA_CENTER), p(sender_name, align=TA_CENTER)],
    ], colWidths=[width * .42, width * .27, width * .31])
    result.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 1), .6, colors.black),
                               ("ALIGN", (1, 1), (-1, -1), "CENTER")]))
    return result


def invoice_story(document, width):
    h = document["header"]
    title = "INVOICE BAHAN BAKU" if document["documentType"] == "BAHAN_BAKU" else "INVOICE OPERASIONAL"
    story = [header(document, title, width=width), Spacer(1, 9)]
    info = Table([
        [p("Penerima: " + str(h.get("recipientName") or "")), p("Pengirim: " + str(h.get("senderName") or h.get("issuerName") or ""))],
        [p("Nama Perusahaan: " + str(h.get("recipientCompany") or "")), p("Nama Perusahaan: " + str(h.get("senderCompany") or ""))],
        [p("Alamat: " + str(h.get("recipientAddress") or "")), ""],
    ], colWidths=[width * .65, width * .35])
    info.setStyle(TableStyle([("SPAN", (0, 2), (-1, 2)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [info, Spacer(1, 10)]
    data = [[p(x, True, TA_CENTER) for x in ("Nama Barang", "Jumlah", "Satuan", "Harga Satuan", "Total Harga")]]
    for item in document["items"]:
        data.append([p(item["itemName"]), p(f"{item['quantity']:g}", align=TA_RIGHT), p(item["unit"]), p(money(item["unitPrice"]), align=TA_RIGHT), p(money(item["lineTotal"]), align=TA_RIGHT)])
    data.append([p("Total Pembayaran", True), "", "", "", p(money(document["total"]), True, TA_RIGHT)])
    table = Table(data, colWidths=[width * .40, width * .10, width * .10, width * .19, width * .21], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .55, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")), ("SPAN", (0, -1), (3, -1)),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [table, Spacer(1, 12), KeepTogether([signatures(document, width=width)])]
    return story


def render_document_pdf(document):
    output = BytesIO()
    pdf = SimpleDocTemplate(output, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=32, bottomMargin=32,
                            title=document["documentNumber"], author=document["header"].get("issuerName") or "SPPG")
    width = A4[0] - 72
    if document["documentType"] in {"BAHAN_BAKU", "OPERASIONAL"}:
        story = invoice_story(document, width)
    else:
        story = []
        for index, item in enumerate(document["items"]):
            metadata = item.get("metadata") or {}
            title = "KUITANSI UPAH RELAWAN" if document["documentType"] == "UPAH_RELAWAN" else "KUITANSI INSENTIF " + str(metadata.get("recipientType") or "Guru").upper()
            detail = metadata.get("role") or metadata.get("unitName") or ""
            receipt = [header(document, title, receipt_number(document, index), width - 18), Spacer(1, 12),
                       p("Telah diterima dari: " + str(document["header"].get("recipientName") or "")),
                       p("Nama penerima: " + item["itemName"], True, size=10), p("Unit / Tugas: " + str(detail)),
                       p("Untuk pembayaran harian tanggal " + date_label(document["serviceDate"]) + " (1 hari)."), Spacer(1, 8),
                       p("Jumlah diterima: " + money(item["lineTotal"]), True, size=12), Spacer(1, 12),
                       signatures(document, recipient=item["itemName"], width=width - 18)]
            box = Table([[receipt]], colWidths=[width])
            box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .65, colors.black), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
            story += [KeepTogether([box]), Spacer(1, 14)]

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(A4[0] - 36, 18, f"{document['documentNumber']} | Halaman {doc.page}")
        if document["status"] != "FINAL":
            canvas.setFillColor(colors.HexColor("#dddddd"))
            canvas.setFont("Helvetica-Bold", 42)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "DRAFT")
        canvas.restoreState()

    pdf.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
