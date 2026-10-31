"""Turn the found fields into a safe, consistent file name."""
from __future__ import annotations

import os
import re
import unicodedata

from .detect import KIND_EXT

DEFAULT_TEMPLATE = "{date}_{type}_{party}_{ref}_{subject}"
TOKENS = ("date", "type", "party", "ref", "subject")
MAX_LEN = 120
PART_MAX = {"party": 30, "ref": 40, "subject": 60, "type": 8, "date": 10}

EXT_ALIASES = {
    "jpg": {".jpg", ".jpeg"}, "tif": {".tif", ".tiff"}, "step": {".step", ".stp"},
    "iges": {".igs", ".iges"}, "txt": {".txt", ".log", ".ini", ".cfg"}, "html": {".html", ".htm"},
    "xlsx": {".xlsx"}, "xlsm": {".xlsm"}, "zip": {".zip"},
}
# Kinds whose detection is generic; keep the sender's extension if it has one.
KEEP_ORIGINAL_EXT = {"txt", "xml", "unknown", "ole", "zip", "html"}

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
                           "&": "and", "+": "plus", "@": "at"})


def validate_template(t: str) -> bool:
    if not re.fullmatch(r"(?:\{(?:date|type|party|ref|subject)\}|[_\-])+", t or ""):
        return False
    return "{date}" in t or "{type}" in t


def safe_part(s: str | None, limit: int = 60) -> str:
    if not s:
        return ""
    s = str(s).translate(_TRANSLIT)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] if "-" in s[:limit] else s[:limit]
    return s.strip("-")


def choose_ext(kind: str, original_name: str) -> str:
    orig = os.path.splitext(original_name or "")[1].lower()
    orig = orig if re.fullmatch(r"\.[a-z0-9]{1,10}", orig or "") else ""
    if kind in KEEP_ORIGINAL_EXT and orig:
        return orig
    if orig and orig in EXT_ALIASES.get(kind, set()):
        return orig
    return KIND_EXT.get(kind, orig)


def sanitize_final(name: str, ext: str) -> str:
    """A name typed by a user: keep their wording, make it safe, and never let the extension change
    (so nobody can turn report.pdf into report.exe)."""
    stem = os.path.basename((name or "").replace("\\", "/"))
    if ext and stem.lower().endswith(ext.lower()):
        stem = stem[: -len(ext)]
    parts = [safe_part(p, 80) for p in stem.split("_")]
    stem = "_".join(p for p in parts if p)[: MAX_LEN - len(ext)].strip("_-") or "file"
    if stem.split(".")[0].upper() in _RESERVED:
        stem = "_" + stem
    return stem + ext


def compose(values: dict, template: str = DEFAULT_TEMPLATE, ext: str = "") -> str:
    """values: {date, type, party, ref, subject} -> 'date_type_party_ref_subject.ext'"""
    if not validate_template(template):
        template = DEFAULT_TEMPLATE
    parts = {k: safe_part(values.get(k), PART_MAX[k]) for k in TOKENS}

    def render(p):
        name = template
        for k in TOKENS:
            name = name.replace("{" + k + "}", p[k])
        name = re.sub(r"[_\-]{2,}", lambda m: "_" if "_" in m.group(0) else "-", name)
        return name.strip("_-")

    name = render(parts)
    budget = MAX_LEN - len(ext)
    for k in ("subject", "ref", "party"):
        while len(name) > budget and parts[k]:
            cut = parts[k].rsplit("-", 1)[0] if "-" in parts[k] else ""
            parts[k] = cut
            name = render(parts)
    name = name[:budget].strip("_-") or "file"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name + ext
