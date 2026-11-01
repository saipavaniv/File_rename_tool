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
    if not (S / "sources.csv").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_samples.py"), str(S)], check=True)
    return {"party_rows": list(csv.DictReader(open(S / "sources.csv"))), "today": "2026-10-31"}


EXPECT = {   # file: (date, type, from, number, title)
    "1706.03762v5.pdf": ("2017-12-06", "PAPER", "Vaswani et al", "arXiv-1706.03762", "Attention Is All You Need"),
    "DA3.pdf": ("2026-10-28", "ASSIGN", "BCSE202L", "Assignment-3", "Linked Lists and Stacks"),
    "QP.pdf": ("2025-11-19", "EXAM", "MAT2002", None, "Applications of Differential and Difference Equations"),
    "certificate.pdf": ("2026-09-12", "CERT", "Coursera", "8XK2QPL7M4ZA", "Machine Learning Specialization"),
    "receipt_1730284112.pdf": ("2026-10-30", "RCPT", "Spotify", "T2610301198745", None),
    "ticket.pdf": ("2026-11-12", "TICKET", None, "4521367890", "Chennai Central to Katpadi Jn"),
    "lec07.pptx": ("2026-10-01", "SLIDES", "CS301", "Lecture-7", "Dynamic Programming"),
    "Document1.docx": ("2026-10-21", "LAB", "CSE3001", "Exp-5", None),
    "main.py": ("2026-10-31", "CODE", None, None, "Dijkstra Shortest Path on a Weighted Graph"),
    "Untitled.ipynb": ("2026-10-31", "NB", None, None, "Linear Regression from Scratch"),
    "mail.eml": ("2026-10-27", "MAIL", "VIT", None, None),
    "Screenshot 2026-10-30 142233.png": ("2026-10-30", "SHOT", None, None, None),
}


@pytest.mark.parametrize("name", list(EXPECT))
def test_fields(name, cfg):
    r = analyse((S / name).read_bytes(), name, {}, cfg)
    f = r["fields"]
    got = tuple(f[k]["value"] for k in ("date", "type", "party", "ref", "subject"))
    exp = EXPECT[name]
    for k, g, e in zip(("date", "type", "party", "ref", "subject"), got, exp):
        if e is not None:
            assert g == e, f"{k}: {g!r} != {e!r}  ({r['suggested_name']})"


def test_code_is_allowed_but_programs_are_not(cfg):
    assert analyse(b"print('hi')", "hello.py", {}, cfg)["status"] != "blocked"
    assert analyse(b"MZ\x90\x00", "notes.pdf", {}, cfg)["status"] == "blocked"
    assert analyse(b"x", "setup.bat", {}, cfg)["status"] == "blocked"


def test_website_is_a_hint(cfg):
    r = analyse(b"Some notes about graphs.\nBFS and DFS.", "graphs.txt", {"page_host": "moodle.vit.ac.in"}, cfg)
    assert r["fields"]["party"]["value"] == "VIT"


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
