"""Read text and metadata out of every supported file type.

Each extractor returns an `Extracted` object. Nothing here executes macros,
follows external links, or writes the file to disk: files are only *read*,
from memory, inside a sandboxed worker process (see pipeline.py).
"""
from __future__ import annotations

import datetime as dt
import email
import email.policy
import json
import email.utils
import html
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import warnings
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .detect import check_zip_safety

for _n in ("pypdf", "extract_msg", "ezdxf", "olefile"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

MAX_TEXT = 1_500_000      # characters kept for analysis
MAX_PAGES = 30            # PDF pages read for text
OCR_PAGES = 3             # scanned pages OCR'd (first pages hold the header)
HEADER_LINES = 30


@dataclass
class Extracted:
    kind: str
    text: str = ""
    header: str = ""                 # top of first page / first rows: where titles, numbers, dates live
    title: str | None = None         # document metadata title
    big_title: str | None = None     # largest text near the top of page 1 (PDF titles, slide headings)
    author: str | None = None
    company: str | None = None       # metadata company (often the author's company)
    meta_dates: list = field(default_factory=list)   # [(date, source)]
    email: dict | None = None        # from_name, from_addr, to, subject, date
    direct: dict = field(default_factory=dict)       # high-confidence structured fields (CAD title blocks, STEP header)
    ocr_used: bool = False
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------- helpers

def _clean(s: str) -> str:
    s = s.replace("\x00", " ").replace("\r", "\n")
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def _head(text: str, n: int = HEADER_LINES) -> str:
    return "\n".join([ln for ln in text.splitlines() if ln.strip()][:n])


def _as_date(v) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


class _TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "table"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(s: str) -> str:
    p = _TextHTML()
    try:
        p.feed(s)
    except Exception:
        return re.sub(r"<[^>]+>", " ", s)
    return html.unescape("".join(p.parts))


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "ignore")
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "ignore")


# ---------------------------------------------------------------- OCR

def ocr_available() -> bool:
    if not shutil.which("tesseract") and not os.environ.get("TESSERACT_CMD"):
        return False
    try:
        import pytesseract  # noqa: F401
        return True
    except ImportError:
        return False


def _ocr_lang() -> str:
    import pytesseract
    if os.environ.get("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        langs = {"eng"}
    return "+".join(l for l in ("eng", "deu") if l in langs) or "eng"


def _ocr_images(images) -> str:
    import pytesseract
    lang = _ocr_lang()
    out = []
    for im in images:
        try:
            out.append(pytesseract.image_to_string(im.convert("L"), lang=lang, timeout=40))
        except Exception:
            continue
    return "\n".join(out)


# ---------------------------------------------------------------- extractors

def _pdf(data: bytes, ex: Extracted):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            ex.warnings.append("PDF is password protected; only file details could be used")
            return
    pages = []
    for page in reader.pages[:MAX_PAGES]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n".join(pages)
    meta = reader.metadata or {}
    try:
        ex.title = (meta.title or "").strip() or None
        ex.author = (meta.author or "").strip() or None
        if meta.creation_date:
            ex.meta_dates.append((meta.creation_date.date(), "PDF creation date"))
    except Exception:
        pass
    if len(text.strip()) < 40:
        if ocr_available():
            try:
                import pypdfium2 as pdfium
                pdf = pdfium.PdfDocument(data)
                imgs = [pdf[i].render(scale=200 / 72).to_pil() for i in range(min(OCR_PAGES, len(pdf)))]
                text = _ocr_images(imgs)
                ex.ocr_used = True
            except Exception:
                ex.warnings.append("Scanned PDF could not be OCR'd")
        else:
            ex.warnings.append("Scanned PDF and OCR (Tesseract) is not installed")
    ex.text = text
    first = pages[0] if pages and pages[0].strip() else text
    ex.header = _head(first)
    if reader.pages and not ex.ocr_used:
        ex.big_title = _pdf_big_title(reader.pages[0])


def _pdf_big_title(page) -> str | None:
    """The title is usually the largest text in the top part of page 1."""
    runs = []
    try:
        height = float(page.mediabox.height)
    except Exception:
        height = 842.0

    def visit(text, cm, tm, font_dict, font_size):
        if not text or not text.strip():
            return
        try:
            scale = (abs(tm[3]) or abs(tm[0]) or 1.0) * (abs(cm[3]) or abs(cm[0]) or 1.0)
            size = float(font_size) * scale
            y = tm[5] * (cm[3] or 1.0) + cm[5]
        except Exception:
            return
        runs.append((round(size, 1), y, text.strip()))

    try:
        page.extract_text(visitor_text=visit)
    except Exception:
        return None
    top = [r for r in runs if r[1] >= height * 0.4 and len(r[2]) >= 2]
    if not top:
        return None
    sizes = sorted({r[0] for r in top}, reverse=True)
    body = sorted(r[0] for r in runs)[len(runs) // 2] if runs else 10
    found = []
    for s in sizes[:4]:
        if s < body * 1.15:      # not noticeably bigger than normal text
            break
        parts = [r[2] for r in sorted((r for r in top if abs(r[0] - s) <= 0.6), key=lambda r: -r[1])]
        title = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if 3 <= len(title) <= 200 and sum(c.isalpha() for c in title) >= 3:
            found.append(title)
    return " || ".join(found[:3]) or None


def _iter_docx_blocks(doc):
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _table_lines(table) -> list[str]:
    lines = []
    for row in table.rows:
        cells, seen = [], set()
        for c in row.cells:
            t = c.text.strip()
            if t and id(c._tc) not in seen:
                cells.append(t.replace("\n", " "))
                seen.add(id(c._tc))
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _docx(data: bytes, ex: Extracted):
    check_zip_safety(data)
    import docx
    from docx.table import Table
    d = docx.Document(io.BytesIO(data))
    header_lines = []
    try:
        sec = d.sections[0]
        for p in sec.header.paragraphs:
            if p.text.strip():
                header_lines.append(p.text.strip())
        for t in sec.header.tables:
            header_lines += _table_lines(t)
    except Exception:
        pass
    body = []
    for block in _iter_docx_blocks(d):
        if isinstance(block, Table):
            body += _table_lines(block)
        elif block.text.strip():
            body.append(block.text.strip())
    footer = []
    try:
        for p in d.sections[0].footer.paragraphs:
            if p.text.strip():
                footer.append(p.text.strip())
    except Exception:
        pass
    ex.text = "\n".join(header_lines + body + footer)
    ex.header = "\n".join((header_lines + body)[:HEADER_LINES])
    cp = d.core_properties
    ex.title = (cp.title or cp.subject or "").strip() or None
    ex.author = (cp.author or "").strip() or None
    if cp.created:
        ex.meta_dates.append((cp.created.date(), "Word file created"))


def _cell_str(v) -> str:
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d") if (v.hour, v.minute) == (0, 0) else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _xlsx(data: bytes, ex: Extracted):
    check_zip_safety(data)
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    lines, header = [], []
    for si, ws in enumerate(wb.worksheets[:5]):
        lines.append(f"[Sheet: {ws.title}]")
        for ri, row in enumerate(ws.iter_rows(max_row=400, max_col=40, values_only=True)):
            cells = [_cell_str(v) for v in row if v is not None and _cell_str(v)]
            if cells:
                ln = " | ".join(cells)
                lines.append(ln)
                if si == 0 and len(header) < HEADER_LINES:
                    header.append(ln)
    ex.text = "\n".join(lines)
    ex.header = "\n".join(header)
    p = wb.properties
    ex.title = (p.title or p.subject or "").strip() or None
    ex.author = (p.creator or "").strip() or None
    if p.created:
        ex.meta_dates.append((p.created.date(), "Excel file created"))
    wb.close()


def _xls(data: bytes, ex: Extracted):
    import xlrd
    wb = xlrd.open_workbook(file_contents=data, on_demand=True)
    lines, header = [], []
    for si in range(min(5, wb.nsheets)):
        sh = wb.sheet_by_index(si)
        lines.append(f"[Sheet: {sh.name}]")
        for r in range(min(sh.nrows, 400)):
            cells = []
            for c in range(min(sh.ncols, 40)):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_EMPTY:
                    continue
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        cells.append(_cell_str(xlrd.xldate.xldate_as_datetime(cell.value, wb.datemode)))
                        continue
                    except Exception:
                        pass
                s = _cell_str(cell.value)
                if s:
                    cells.append(s)
            if cells:
                lines.append(" | ".join(cells))
                if si == 0 and len(header) < HEADER_LINES:
                    header.append(lines[-1])
    ex.text = "\n".join(lines)
    ex.header = "\n".join(header)
    _ole_meta(data, ex)


def _pptx(data: bytes, ex: Extracted):
    check_zip_safety(data)
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    slides = []
    for s in list(prs.slides)[:60]:
        parts = []
        for shp in s.shapes:
            if shp.has_text_frame and shp.text_frame.text.strip():
                parts.append(shp.text_frame.text.strip())
        slides.append("\n".join(parts))
    ex.text = "\n".join(slides)
    ex.header = _head(slides[0] if slides else "")
    try:
        first = list(prs.slides)[0]
        if first.shapes.title is not None and first.shapes.title.text.strip():
            ex.big_title = first.shapes.title.text.strip()
    except Exception:
        pass
    cp = prs.core_properties
    ex.title = (cp.title or "").strip() or None
    ex.author = (cp.author or "").strip() or None
    if cp.created:
        ex.meta_dates.append((cp.created.date(), "PowerPoint file created"))


def _odf(data: bytes, ex: Extracted):
    zf = check_zip_safety(data)
    from defusedxml import ElementTree as ET
    root = ET.fromstring(zf.read("content.xml"))
    parts = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("p", "h") and "".join(el.itertext()).strip():
            parts.append("".join(el.itertext()).strip())
    ex.text = "\n".join(parts)
    ex.header = _head(ex.text)


def _ole_meta(data: bytes, ex: Extracted):
    try:
        import olefile
        ole = olefile.OleFileIO(io.BytesIO(data))
        m = ole.get_metadata()
        ole.close()
    except Exception:
        return
    def s(v):
        if isinstance(v, bytes):
            return v.decode("cp1252", "ignore").strip() or None
        return (v or None) if isinstance(v, str) else None
    ex.title = ex.title or s(m.title) or s(m.subject)
    ex.author = ex.author or s(m.author)
    ex.company = ex.company or s(getattr(m, "company", None))
    if isinstance(m.create_time, dt.datetime) and m.create_time.year > 1990:
        ex.meta_dates.append((m.create_time.date(), "file created"))


def _ole_strings(data: bytes, ex: Extracted, stream_names=("WordDocument", "PowerPoint Document")):
    """Legacy .doc/.ppt: pull readable text runs out of the binary streams."""
    try:
        import olefile
        ole = olefile.OleFileIO(io.BytesIO(data))
        raw = b""
        for name in stream_names:
            if ole.exists(name):
                raw += ole.openstream(name).read()[:20_000_000]
        ole.close()
    except Exception:
        raw = data
    utf16 = re.findall(rb"(?:[\x20-\x7e\xc0-\xff]\x00){4,}", raw)
    ascii_ = re.findall(rb"[\x20-\x7e\xc0-\xff\r\n\t]{6,}", raw)
    text = "\n".join([u.decode("utf-16le", "ignore") for u in utf16] + [a.decode("cp1252", "ignore") for a in ascii_])
    ex.text = text
    ex.header = _head(text)
    _ole_meta(data, ex)
    ex.warnings.append("Old binary Office format: text read approximately")


def _msg(data: bytes, ex: Extracted):
    import extract_msg
    msg = extract_msg.Message(data)
    try:
        sender = msg.sender or ""
        name, addr = email.utils.parseaddr(sender)
        d = msg.date
        if isinstance(d, str):
            try:
                d = email.utils.parsedate_to_datetime(d)
            except Exception:
                d = None
        body = msg.body or ""
        if not body.strip() and msg.htmlBody:
            hb = msg.htmlBody
            body = html_to_text(hb.decode("utf-8", "ignore") if isinstance(hb, bytes) else hb)
        atts = [getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or "" for a in msg.attachments]
        ex.email = {"from_name": name or sender, "from_addr": addr.lower(), "to": msg.to or "",
                    "subject": (msg.subject or "").strip(), "date": _as_date(d)}
        ex.text = f"Subject: {ex.email['subject']}\nFrom: {sender}\n{body}\nAttachments: {', '.join(a for a in atts if a)}"
        ex.header = _head(ex.text)
    finally:
        try:
            msg.close()
        except Exception:
            pass


def _eml(data: bytes, ex: Extracted):
    msg = email.message_from_bytes(data, policy=email.policy.default)
    name, addr = email.utils.parseaddr(str(msg.get("From", "")))
    d = None
    try:
        d = email.utils.parsedate_to_datetime(str(msg.get("Date")))
    except Exception:
        pass
    body = ""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            body = part.get_content()
            if part.get_content_type() == "text/html":
                body = html_to_text(body)
    except Exception:
        pass
    atts = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    subject = str(msg.get("Subject", "")).strip()
    ex.email = {"from_name": name, "from_addr": addr.lower(), "to": str(msg.get("To", "")),
                "subject": subject, "date": _as_date(d)}
    ex.text = f"Subject: {subject}\nFrom: {name} <{addr}>\n{body}\nAttachments: {', '.join(atts)}"
    ex.header = _head(ex.text)


# Title-block attribute tags commonly used in CAD templates (EN + DE).
_TB = {
    "ref": ["DWG_NO", "DWGNO", "DRAWING_NO", "DRAWINGNO", "DRAWING_NUMBER", "DRAWINGNUMBER", "DRG_NO", "DOC_NO",
            "ZEICHNUNGSNR", "ZEICHNUNGS-NR", "ZEICHNUNGSNUMMER", "ZNR", "PART_NO", "PARTNO", "PART_NUMBER",
            "TEILENR", "SACHNUMMER", "SACHNR", "ITEM_NO", "NUMBER", "NR"],
    "rev": ["REV", "REVISION", "INDEX", "AENDERUNGSINDEX", "ÄNDERUNGSINDEX", "ISSUE", "VERSION"],
    "subject": ["TITLE", "TITLE1", "DESCRIPTION", "BENENNUNG", "BEZEICHNUNG", "PART_NAME", "PARTNAME", "NAME", "TITEL"],
    "date": ["DATE", "DATUM", "DRAWN_DATE", "DRAWNDATE", "CREATED", "ERSTELLT", "DATE_DRAWN"],
    "party": ["CUSTOMER", "KUNDE", "CLIENT", "COMPANY", "FIRMA", "OWNER"],
}


def _dxf(data: bytes, ex: Extracted):
    from ezdxf import recover
    doc, _aud = recover.read(io.BytesIO(data))
    texts, attribs = [], {}
    layouts = [doc.modelspace()] + [doc.layouts.get(n) for n in doc.layouts.names() if n.lower() != "model"]
    count = 0
    for lay in layouts:
        for e in lay:
            count += 1
            if count > 200_000:
                break
            t = e.dxftype()
            try:
                if t == "TEXT":
                    texts.append(e.dxf.text)
                elif t == "MTEXT":
                    texts.append(e.plain_text())
                elif t == "INSERT":
                    for a in e.attribs:
                        tag, val = a.dxf.tag.upper().strip(), a.dxf.text.strip()
                        if val:
                            attribs[tag] = val
                            texts.append(f"{tag}: {val}")
            except Exception:
                continue
    ex.text = "\n".join(t for t in texts if t and t.strip())
    ex.header = ex.text[:4000]
    for fld, tags in _TB.items():
        for tag in tags:
            if tag in attribs:
                ex.direct.setdefault(fld, (attribs[tag], f"CAD title block field {tag}"))
                break
    try:
        from ezdxf.tools.juliandate import calendardate
        jd = doc.header.get("$TDCREATE")
        if jd:
            ex.meta_dates.append((calendardate(float(jd)).date(), "CAD file created"))
        ex.author = doc.header.get("$LASTSAVEDBY") or None
    except Exception:
        pass


def _dwg(data: bytes, ex: Extracted):
    conv = os.environ.get("ODA_FILE_CONVERTER")
    if conv and shutil.which(conv) or (conv and os.path.isfile(conv)):
        with tempfile.TemporaryDirectory() as tin, tempfile.TemporaryDirectory() as tout:
            p = os.path.join(tin, "in.dwg")
            with open(p, "wb") as f:
                f.write(data)
            try:
                subprocess.run([conv, tin, tout, "ACAD2018", "DXF", "0", "0"], timeout=60,
                               capture_output=True, check=False)
                outs = [f for f in os.listdir(tout) if f.lower().endswith(".dxf")]
                if outs:
                    with open(os.path.join(tout, outs[0]), "rb") as f:
                        _dxf(f.read(), ex)
                    ex.kind = "dwg"
                    return
            except Exception:
                pass
    ex.warnings.append("DWG drawing content is not readable without the ODA File Converter; using file details only")
    ex.text = " ".join(s.decode("latin-1") for s in re.findall(rb"[\x20-\x7e]{8,}", data[:2_000_000])[:500])


def _step_str(s: str) -> str:
    s = s.replace("''", "'")
    def x2(m):
        h = m.group(1)
        try:
            return bytes.fromhex(h).decode("utf-16-be")
        except Exception:
            return ""
    s = re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\", x2, s)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("latin-1"), s)
    return s.strip()


def _step(data: bytes, ex: Extracted):
    text = data[:3_000_000].decode("latin-1", "ignore")
    hdr = re.search(r"HEADER;(.*?)ENDSEC;", text, re.S)
    h = hdr.group(1) if hdr else ""
    strs = lambda s: [_step_str(m) for m in re.findall(r"'((?:[^']|'')*)'", s)]
    fn = re.search(r"FILE_NAME\s*\((.*?)\);", h, re.S)
    parts = []
    if fn:
        vals = strs(fn.group(1))
        # name, timestamp, author(s), organization(s), preprocessor, originating system, authorisation
        if vals:
            name = vals[0]
            if name:
                ex.title = re.sub(r"\.(stp|step)$", "", os.path.basename(name.replace("\\", "/")), flags=re.I)
            if len(vals) > 1:
                m = re.match(r"(\d{4})-(\d{2})-(\d{2})", vals[1])
                if m:
                    try:
                        ex.meta_dates.append((dt.date(*map(int, m.groups())), "STEP file timestamp"))
                    except ValueError:
                        pass
            if len(vals) > 2:
                ex.author = vals[2] or None
            if len(vals) > 3 and vals[3]:
                ex.company = vals[3]
            parts += [v for v in vals if v]
    fd = re.search(r"FILE_DESCRIPTION\s*\((.*?)\);", h, re.S)
    if fd:
        parts += [v for v in strs(fd.group(1)) if v and not re.fullmatch(r"\d;\d", v)]
    prod = re.search(r"=\s*PRODUCT\s*\(\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'", text)
    if prod:
        pid, pname = _step_str(prod.group(1)), _step_str(prod.group(2))
        if pname:
            ex.direct["subject"] = (pname, "STEP product name")
        if pid and re.search(r"\d", pid) and pid != pname:
            ex.direct["ref"] = (pid, "STEP product id")
        elif re.search(r"\d", pname) and re.fullmatch(r"[A-Za-z0-9._\-/]{4,40}", pname):
            ex.direct["ref"] = (pname, "STEP product name")
        parts += [pid, pname]
    ex.text = "\n".join(p for p in parts if p)
    ex.header = ex.text


def _hollerith(s: str) -> list[str]:
    out, i = [], 0
    while i < len(s):
        m = re.match(r"\s*(\d+)H", s[i:])
        if m:
            n = int(m.group(1))
            start = i + m.end()
            out.append(s[start:start + n])
            i = start + n
        else:
            j = s.find(",", i)
            if j == -1:
                out.append(s[i:].strip(" ;"))
                break
            out.append(s[i:j].strip())
            i = j
        if i < len(s) and s[i] in ",;":
            i += 1
    return out


def _iges(data: bytes, ex: Extracted):
    text = data[:2_000_000].decode("latin-1", "ignore")
    start, glob = [], []
    for ln in text.splitlines()[:400]:
        if len(ln) >= 73:
            sec = ln[72]
            if sec == "S":
                start.append(ln[:72].strip())
            elif sec == "G":
                glob.append(ln[:72])
            elif sec == "D":
                break
    g = _hollerith("".join(glob))
    parts = [s for s in start if s]
    if len(g) > 3 and g[3]:
        ex.title = re.sub(r"\.(igs|iges)$", "", os.path.basename(g[3].replace("\\", "/")), flags=re.I)
    if len(g) > 20:
        ex.author = g[20] or None
    if len(g) > 21:
        ex.company = g[21] or None
    if len(g) > 17:
        m = re.match(r"(\d{2,4})(\d{2})(\d{2})", g[17] or "")
        if m:
            y = int(m.group(1))
            y = y + 1900 if y < 100 else y
            try:
                ex.meta_dates.append((dt.date(y, int(m.group(2)), int(m.group(3))), "IGES file date"))
            except ValueError:
                pass
    ex.text = "\n".join(parts + [x for x in g if x and len(x) > 2])
    ex.header = ex.text


def _image(data: bytes, ex: Extracted):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 120_000_000
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        im = Image.open(io.BytesIO(data))
        im.load()
    try:
        exif = im.getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if raw:
            m = re.match(r"(\d{4}):(\d{2}):(\d{2})", str(raw))
            if m:
                ex.meta_dates.append((dt.date(*map(int, m.groups())), "photo taken"))
    except Exception:
        pass
    if ocr_available():
        if getattr(im, "n_frames", 1) > 1:
            frames = []
            for i in range(min(OCR_PAGES, im.n_frames)):
                im.seek(i)
                frames.append(im.copy())
        else:
            frames = [im]
        ex.text = _ocr_images(frames)
        ex.ocr_used = True
        ex.header = _head(ex.text)
    else:
        ex.warnings.append("Image text can't be read because OCR (Tesseract) is not installed")


def _rtf(data: bytes, ex: Extracted):
    s = _decode(data)
    s = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "ignore"), s)
    s = re.sub(r"\\par[d]?", "\n", s)
    s = re.sub(r"\{\\\*[^{}]*\}", "", s)
    s = re.sub(r"\\[a-z]+-?\d* ?", "", s)
    s = s.replace("{", "").replace("}", "")
    ex.text = s
    ex.header = _head(s)


def _zip(data: bytes, ex: Extracted):
    zf = check_zip_safety(data)
    names = [i.filename for i in zf.infolist() if not i.is_dir()][:300]
    ex.text = "Archive contents:\n" + "\n".join(os.path.basename(n) for n in names)
    ex.header = ex.text
    dates = [dt.date(*i.date_time[:3]) for i in zf.infolist() if i.date_time[0] > 1990]
    if dates:
        ex.meta_dates.append((max(dates), "newest file in archive"))


def _ipynb(data: bytes, ex: Extracted):
    nb = json.loads(data[:20_000_000].decode("utf-8", "ignore"))
    md, code = [], []
    for cell in (nb.get("cells") or [])[:500]:
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        (md if cell.get("cell_type") == "markdown" else code).append(src)
    for block in md:
        m = re.search(r"^\s*#{1,3}\s+(.+)$", block, re.M)
        if m:
            ex.title = m.group(1).strip()
            break
    ex.text = "\n".join(md + code)
    ex.header = _head("\n".join(md[:3]) or ex.text)


def _plain(data: bytes, ex: Extracted, kind: str):
    s = _decode(data[:5_000_000])
    if kind == "html":
        s = html_to_text(s)
    elif kind == "xml":
        s = re.sub(r"<[^>]+>", " ", s)
    ex.text = s
    ex.header = _head(s)


EXTRACTORS = {
    "pdf": _pdf, "docx": _docx, "xlsx": _xlsx, "xlsm": _xlsx, "xls": _xls, "pptx": _pptx,
    "odt": _odf, "ods": _odf, "doc": _ole_strings, "ppt": _ole_strings, "msg": _msg, "eml": _eml,
    "dxf": _dxf, "dwg": _dwg, "step": _step, "iges": _iges, "png": _image, "jpg": _image,
    "tif": _image, "gif": _image, "bmp": _image, "rtf": _rtf, "zip": _zip, "ipynb": _ipynb,
}


def extract(data: bytes, kind: str) -> Extracted:
    ex = Extracted(kind=kind)
    fn = EXTRACTORS.get(kind)
    try:
        if fn:
            fn(data, ex)
        elif kind in ("txt", "csv", "html", "xml", "json"):
            _plain(data, ex, kind)
        elif kind == "ole":
            _ole_meta(data, ex)
        else:
            ex.warnings.append("File type not readable; name is based on file details only")
    except Exception as e:  # never let one bad file crash the service
        ex.warnings.append(f"Could not fully read this file ({type(e).__name__})")
    ex.text = _clean(ex.text)[:MAX_TEXT]
    ex.header = _clean(ex.header)[:8000]
    return ex
