"""Identify what a file really is from its bytes (not its extension).

Returning a 'kind' lets the pipeline pick the right extractor and lets the
namer put the *correct* extension on the output, even if the sender used a
wrong one or none at all.
"""
from __future__ import annotations

import io
import zipfile

# Correct extension to use for each detected kind.
KIND_EXT = {
    "pdf": ".pdf", "docx": ".docx", "xlsx": ".xlsx", "xlsm": ".xlsm", "pptx": ".pptx",
    "odt": ".odt", "ods": ".ods", "doc": ".doc", "xls": ".xls", "ppt": ".ppt",
    "msg": ".msg", "eml": ".eml", "dxf": ".dxf", "dwg": ".dwg", "step": ".step",
    "iges": ".igs", "png": ".png", "jpg": ".jpg", "tif": ".tif", "gif": ".gif",
    "bmp": ".bmp", "zip": ".zip", "7z": ".7z", "rar": ".rar", "rtf": ".rtf",
    "csv": ".csv", "txt": ".txt", "html": ".html", "xml": ".xml", "ipynb": ".ipynb", "json": ".json",
}

# Zip-bomb guard for Office/zip containers.
MAX_UNCOMPRESSED = 400 * 1024 * 1024
MAX_RATIO = 200
MAX_MEMBERS = 5000


# Programs and scripts are never renamed: a renamed .hta/.exe looking like an invoice is a phishing gift.
DANGEROUS_EXT = {
    ".exe", ".com", ".scr", ".pif", ".msi", ".msp", ".msc", ".dll", ".cpl", ".sys", ".drv", ".ocx",
    ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".jse", ".wsf", ".wsh", ".hta",
    ".lnk", ".url", ".reg", ".inf", ".jar", ".appx", ".msix", ".application", ".gadget", ".iso", ".img",
    ".vhd", ".vhdx", ".app", ".dmg", ".pkg", ".deb", ".rpm", ".apk",
    ".docm", ".dotm", ".xlam", ".pptm", ".ppam", ".chm", ".settingcontent-ms", ".library-ms",
}
# Source code is welcome (it's only read, never run).
CODE_EXT = {
    ".py", ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".cs", ".js", ".mjs", ".ts", ".jsx", ".tsx",
    ".go", ".rs", ".rb", ".php", ".kt", ".swift", ".scala", ".r", ".m", ".sql", ".sh", ".html", ".htm",
    ".css", ".scss", ".lua", ".dart", ".hs", ".pl", ".asm", ".s", ".v", ".sv", ".ino", ".f90",
}


class UnsafeFile(Exception):
    """Raised when a file looks hostile (zip bomb, malformed container)."""


def check_zip_safety(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UnsafeFile("damaged zip container") from e
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise UnsafeFile("too many entries in container")
    total = sum(i.file_size for i in infos)
    packed = max(1, sum(i.compress_size for i in infos))
    if total > MAX_UNCOMPRESSED or total / packed > MAX_RATIO:
        raise UnsafeFile("container expands to an unsafe size (possible zip bomb)")
    for i in infos:
        if i.filename.startswith("/") or ".." in i.filename.replace("\\", "/").split("/"):
            raise UnsafeFile("container has unsafe paths")
    return zf


def _ole_kind(data: bytes) -> str:
    try:
        import olefile
        ole = olefile.OleFileIO(io.BytesIO(data))
        names = {"/".join(e).lower() for e in ole.listdir(streams=True, storages=True)}
        ole.close()
    except Exception:
        return "ole"
    if any(n.startswith("__substg1.0_") for n in names) or "__properties_version1.0" in names:
        return "msg"
    if "worddocument" in names:
        return "doc"
    if "workbook" in names or "book" in names:
        return "xls"
    if "powerpoint document" in names:
        return "ppt"
    return "ole"


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return False
    if b"\x00" in head[:4096]:
        # allow UTF-16 text
        return head[:2] in (b"\xff\xfe", b"\xfe\xff")
    printable = sum(1 for b in head[:4096] if b in (9, 10, 13) or 32 <= b < 127 or b >= 128)
    return printable / min(len(head), 4096) > 0.95


def detect_kind(data: bytes, filename: str = "") -> str:
    head = data[:8192]
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if head.startswith(b"MZ") or head.startswith(b"\x7fELF") or head[:4] in (b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe"):
        return "exe"
    if head.startswith(b"%PDF") or b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        zf = check_zip_safety(data)
        names = set(zf.namelist())
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsm" if "xl/vbaProject.bin" in names else "xlsx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        if "mimetype" in names:
            mt = zf.read("mimetype")[:100]
            if b"opendocument.text" in mt:
                return "odt"
            if b"opendocument.spreadsheet" in mt:
                return "ods"
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return _ole_kind(data)
    if head[:4] in (b"AC10",) or head[:6] in (b"AC1012", b"AC1014", b"AC1015", b"AC1018", b"AC1021", b"AC1024", b"AC1027", b"AC1032"):
        return "dwg"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tif"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head.startswith(b"BM") and ext == "bmp":
        return "bmp"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head.startswith(b"Rar!"):
        return "rar"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"AutoCAD Binary DXF"):
        return "dxf"

    if _looks_like_text(head):
        text = head.decode("latin-1", "ignore")
        stripped = text.lstrip()
        if stripped.startswith("{") and '"cells"' in data[:2_000_000].decode("utf-8", "ignore") and '"nbformat"' in data[-20000:].decode("utf-8", "ignore") + text:
            return "ipynb"
        if stripped.startswith("ISO-10303-21"):
            return "step"
        lines = [ln.strip() for ln in stripped.splitlines()[:4]]
        if len(lines) >= 2 and lines[0] == "0" and lines[1].upper() == "SECTION":
            return "dxf"
        if ext in ("igs", "iges") or (len(text) > 80 and text[72:73] == "S" and text[73:80].strip().isdigit()):
            return "iges"
        low = text[:3000].lower()
        hdrs = sum(1 for h in ("\nfrom:", "\nsubject:", "\ndate:", "\nto:", "mime-version:", "\nreceived:", "message-id:")
                   if h in "\n" + low)
        if hdrs >= 3:
            return "eml"
        if stripped[:15].lower().startswith(("<!doctype html", "<html")):
            return "html"
        if stripped.startswith("<?xml"):
            return "xml"
        if stripped[:1] in ("{", "[") and ext == "json":
            return "json"
        if ext == "csv":
            return "csv"
        return "txt"
    return "unknown"
