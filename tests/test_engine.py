"""Naming-engine accuracy tests on the generated sample files.  Run:  python -m pytest -q"""
import csv
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.engine.naming import compose, safe_part, sanitize_final  # noqa: E402
from app.engine.pipeline import analyse  # noqa: E402

S = ROOT / "samples"


@pytest.fixture(scope="module")
def cfg():
    if not (S / "parties.csv").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_samples.py"), str(S)], check=True)
    return {"party_rows": list(csv.DictReader(open(S / "parties.csv"))), "today": "2026-10-30"}


EXPECT = {
    "Document1.pdf": ("2026-10-28", "QUO", "Precitool", "PTC/Q/2026/0457"),
    "Document2.docx": ("2026-10-14", "PO", "Lumen-Auto", "4500098123"),
    "Book1.xlsx": ("2026-10-21", "INV", "Sri Balaji Metals", "SBM/2026-27/1189"),
    "mail.eml": ("2026-10-27", "MAIL", "Lumen-Auto", "77812"),
    "export.dxf": ("2026-09-15", "DRW", "Lumen-Auto", "KR-4711-02 RevC"),
    "Part1.stp": ("2026-10-02", "CAD", "Lumen-Auto", "7781-2210"),
    "scan_0034.pdf": ("2026-10-02", "CERT", "Wieland", "MTC-88231"),   # scanned: needs Tesseract
    "Document3.docx": ("2026-10-22", "MOM", "Lumen-Auto", None),
}


@pytest.mark.parametrize("name", list(EXPECT))
def test_fields(name, cfg):
    from app.engine.extract import ocr_available
    if name.startswith("scan") and not ocr_available():
        pytest.skip("Tesseract not installed")
    r = analyse((S / name).read_bytes(), name, {}, cfg)
    f = r["fields"]
    got = (f["date"]["value"], f["type"]["value"], f["party"]["value"], f["ref"]["value"])
    assert got == EXPECT[name], r["suggested_name"]
    assert r["status"] == "auto"


def test_document_beats_page_sender(cfg):
    r = analyse((S / "Book1.xlsx").read_bytes(), "Book1.xlsx", {"sender_emails": ["a@lumen-auto.de"]}, cfg)
    assert r["fields"]["party"]["value"] == "Sri Balaji Metals"


def test_zip_bomb(cfg):
    assert analyse((S / "bomb.docx").read_bytes(), "bomb.docx", {}, cfg)["status"] == "blocked"


def test_junk_never_crashes(cfg):
    import os
    for data in (b"", os.urandom(4000), b"%PDF-1.4 broken", b"PK\x03\x04garbage", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1junk"):
        r = analyse(data, "x.bin", {}, cfg)
        assert r["status"] in ("review", "blocked")


def test_names_are_safe():
    assert safe_part("Gehäuse / Größe: 12\"") == "Gehaeuse-Groesse-12"
    assert compose({"date": "2026-01-02", "type": "PO", "party": None, "ref": "A/1", "subject": ""}, ext=".pdf") == "2026-01-02_PO_A-1.pdf"
    assert sanitize_final("..\\..\\x.exe", ".pdf") == "x-exe.pdf"
    assert sanitize_final("CON", ".txt") == "_CON.txt"
    long = compose({"date": "2026-01-02", "type": "QUO", "party": "P" * 40, "ref": "R" * 50, "subject": "word " * 40}, ext=".docx")
    assert len(long) <= 120 and long.endswith(".docx")
