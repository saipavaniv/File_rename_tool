"""Generate realistic sample files (fictional companies) to test the naming engine.

Usage:  python scripts/make_samples.py  [output_dir]
"""
import io
import os
import sys
import zipfile
from email.message import EmailMessage

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "samples")
os.makedirs(OUT, exist_ok=True)


def p(name):
    return os.path.join(OUT, name)


def quotation_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(p("Document1.pdf"), pagesize=A4)
    c.setTitle("")
    y = 800
    def line(t, size=10, bold=False, dy=16):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(50, y, t)
        y -= dy
    line("PRECITOOL Components Pvt. Ltd.", 14, True, 18)
    line("No. 14, Industrial Estate, Ambattur, Chennai 600058  |  GSTIN 33AABCP1234Q1Z5")
    line("Tel +91 44 2625 1100  |  sales@precitool.in", dy=30)
    line("QUOTATION", 16, True, 26)
    line("Quotation No: PTC/Q/2026/0457")
    line("Date: 28.10.2026")
    line("Valid until: 30.11.2026", dy=24)
    line("To:")
    line("KRAMSKI India Pvt. Ltd.")
    line("SIPCOT Industrial Complex, Vellore, Tamil Nadu", dy=24)
    line("Subject: Progressive die for contact spring KR-5520", bold=True, dy=24)
    line("Dear Sir, with reference to your enquiry dated 15.10.2026 we are pleased to offer:")
    line("1. Progressive stamping die, 12 stations, carbide punches      INR 18,40,000")
    line("2. Trial run and sample submission (50 pcs)                     INR   65,000")
    line("Payment terms: 40% advance, balance before dispatch. Delivery date: 15.01.2027", dy=24)
    line("For PRECITOOL Components Pvt. Ltd.")
    c.save()


def po_docx():
    import docx
    d = docx.Document()
    d.sections[0].header.paragraphs[0].text = "Lumen Automotive Systems GmbH · Industriestraße 7 · 75179 Pforzheim"
    d.add_heading("Bestellung", 0)
    t = d.add_table(rows=3, cols=2)
    for i, (a, b) in enumerate([("Bestellnummer", "4500098123"), ("Datum", "14.10.2026"), ("Lieferant", "KRAMSKI GmbH")]):
        t.cell(i, 0).text, t.cell(i, 1).text = a, b
    d.add_paragraph("Betreff: Steckverbinder Gehäuse 12-polig, Serienlieferung")
    d.add_paragraph("Sehr geehrte Damen und Herren, bitte liefern Sie gemäß Ihrem Angebot Nr. KR-A-2026-311:")
    d.add_paragraph("Pos 10: Gehäuse 12-polig, Sachnummer 7781-2210, 50.000 Stück, Liefertermin 30.11.2026")
    d.core_properties.title = ""
    d.save(p("Document2.docx"))


def invoice_xlsx():
    import datetime as dt
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Invoice"
    rows = [["Sri Balaji Metals Pvt Ltd"], ["Katpadi Road, Vellore 632007"], [], ["TAX INVOICE"],
            ["Invoice No", "SBM/2026-27/1189"], ["Invoice Date", dt.datetime(2026, 10, 21)],
            ["Bill To", "Kramski India Pvt. Ltd., Vellore"], [],
            ["Description", "HSN", "Qty (kg)", "Rate", "Amount"],
            ["CuSn6 strip 0.3 x 42 mm", "7409", 850, 912, 775200],
            ["", "", "", "CGST 9%", 69768], ["", "", "", "SGST 9%", 69768],
            ["", "", "", "Total amount payable", 914736]]
    for r in rows:
        ws.append(r)
    wb.save(p("Book1.xlsx"))


def complaint_eml():
    m = EmailMessage()
    m["From"] = "Anna Schmidt <anna.schmidt@lumen-auto.de>"
    m["To"] = "quality@kramski.com"
    m["Subject"] = "AW: 8D Report complaint 77812 - contact pin deformation"
    m["Date"] = "Tue, 27 Oct 2026 09:14:03 +0100"
    m["Message-ID"] = "<abc123@lumen-auto.de>"
    m.set_content("Hello team,\n\nplease find attached our updated 8D report for complaint no. 77812.\n"
                  "Containment action must be confirmed by Friday.\n\nBest regards\nAnna Schmidt\n"
                  "Lumen Automotive Systems GmbH\nQuality Management")
    m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="8D_77812.pdf")
    with open(p("mail.eml"), "wb") as f:
        f.write(bytes(m))


def drawing_dxf():
    import ezdxf
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 12), (0, 12)], close=True)
    blk = doc.blocks.new(name="TITLEBLOCK")
    for i, tag in enumerate(["DWG_NO", "TITLE", "REV", "DATE", "CUSTOMER", "SCALE"]):
        blk.add_attdef(tag, (0, -i * 5), dxfattribs={"height": 2.5})
    ins = msp.add_blockref("TITLEBLOCK", (100, 50))
    ins.add_auto_attribs({"DWG_NO": "KR-4711-02", "TITLE": "Contact spring 0.64 mm", "REV": "C",
                          "DATE": "15.09.2026", "CUSTOMER": "Lumen Automotive", "SCALE": "5:1"})
    msp.add_text("GENERAL TOLERANCES ISO 2768-mK", dxfattribs={"height": 2}).set_placement((100, 10))
    doc.saveas(p("export.dxf"))


def model_step():
    s = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('CATIA V5 STEP Exchange'),'2;1');
FILE_NAME('C:\\\\Temp\\\\Part1.stp','2026-10-02T11:20:44',('rkumar'),('Lumen Automotive Systems'),'ST-DEVELOPER v18','CATIA Version 5 Release 2023','none');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));
ENDSEC;
DATA;
#1=PRODUCT('7781-2210','Housing 12-pole connector','',(#2));
ENDSEC;
END-ISO-10303-21;
"""
    with open(p("Part1.stp"), "w") as f:
        f.write(s)


def scanned_certificate():
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("L", (1654, 2339), 255)  # A4 @ 200 dpi
    dr = ImageDraw.Draw(im)
    try:
        font_b = ImageFont.truetype("DejaVuSans-Bold.ttf", 46)
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font_b = font = ImageFont.load_default()
    y = 140
    for t, f in [("Wieland Werke AG", font_b), ("Graf-Arco-Strasse 36, 89079 Ulm, Germany", font),
                 ("", font), ("MATERIAL TEST CERTIFICATE", font_b), ("Inspection certificate EN 10204 3.1", font),
                 ("", font), ("Certificate No: MTC-88231", font), ("Date: 02.10.2026", font),
                 ("Customer: KRAMSKI India Pvt. Ltd.", font), ("Material: CuSn6 R420, strip 0.30 x 42.0 mm", font),
                 ("Heat No: 51123", font), ("Tensile strength 452 MPa   Hardness 141 HV", font)]:
        dr.text((140, y), t, fill=0, font=f)
        y += 70
    im.save(p("scan_0034.pdf"), "PDF", resolution=200)


def minutes_docx():
    import docx
    d = docx.Document()
    d.add_heading("Minutes of Meeting", 0)
    d.add_paragraph("Date: 22 October 2026")
    d.add_paragraph("Attendees: R. Kumar, S. Iyer, Anna Schmidt (Lumen Automotive Systems GmbH)")
    d.add_paragraph("Subject: PPAP timeline for housing 12-pole")
    d.add_paragraph("Action items: submit PSW by 10.11.2026; capability study on cavity 4.")
    d.save(p("Document3.docx"))


def zip_bomb():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * (60 * 1024 * 1024))
    with open(p("bomb.docx"), "wb") as f:
        f.write(buf.getvalue())


if __name__ == "__main__":
    for fn in (quotation_pdf, po_docx, invoice_xlsx, complaint_eml, drawing_dxf, model_step,
               scanned_certificate, minutes_docx, zip_bomb):
        fn()
    with open(p("parties.csv"), "w") as f:
        f.write("code,name,short_name,aliases,domains,kind\n"
                "C1001,Lumen Automotive Systems GmbH,Lumen-Auto,Lumen Automotive;LAS,lumen-auto.de,customer\n"
                "S2001,Precitool Components Pvt. Ltd.,Precitool,,precitool.in,supplier\n"
                "S2002,Wieland-Werke AG,Wieland,Wieland Werke,wieland.com,supplier\n")
    print("samples written to", os.path.abspath(OUT))
