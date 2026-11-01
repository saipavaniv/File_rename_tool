"""Find the five naming fields in an extracted document.

Every field is chosen by scoring candidates with transparent rules:
  * where it was found (title/header beats body text),
  * what label sits next to it ("Invoice No:", "Datum:", "Customer:"),
  * whether it matches your list of known sources (courses, colleges, companies),
  * the email around the file (sender, subject, date).
Each result carries the evidence, so the UI can show *why* a name was chosen.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .extract import Extracted

RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.json")


@lru_cache(maxsize=1)
def rules() -> dict:
    with open(RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Field:
    value: str | None = None
    confidence: float = 0.0
    source: str = ""
    alternatives: list = field(default_factory=list)

    def as_dict(self):
        return {"value": self.value, "confidence": round(self.confidence, 2),
                "source": self.source, "alternatives": self.alternatives[:4]}


@dataclass
class Cand:
    value: object
    score: float
    source: str


def _best(cands: list[Cand], key=lambda c: c.value) -> tuple[Cand | None, list[Cand]]:
    """Merge duplicate candidates (sum scores, cap repetition bonus) and rank."""
    merged: dict = {}
    for c in cands:
        k = key(c)
        if k in merged:
            m = merged[k]
            m.score = max(m.score, c.score) + min(1.0, 0.3 * min(c.score, m.score) / max(m.score, 1e-9))
        else:
            merged[k] = Cand(c.value, c.score, c.source)
    ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)
    return (ranked[0] if ranked else None), ranked


def _conf(score: float, runner: float | None, scale: float) -> float:
    strength = min(1.0, score / scale)
    margin = 1.0 if not runner else max(0.0, (score - runner) / score)
    return round(min(0.97, 0.25 + 0.5 * strength + 0.22 * margin), 2)


# ================================================================ context helpers

def _lines(ex: Extracted):
    header = [ln.strip() for ln in ex.header.splitlines() if ln.strip()]
    hset = set(header)
    body = [ln.strip() for ln in ex.text.splitlines() if ln.strip()]
    return header, hset, body


def _label_re(labels: list[str]) -> re.Pattern:
    alts = sorted((re.escape(l) for l in labels), key=len, reverse=True)
    return re.compile(r"(?<![\w])(?:" + "|".join(alts) + r")(?![\w])", re.I)


def is_generic_filename(stem: str) -> bool:
    s = stem.lower().strip()
    s = re.sub(r"\s*\(\d+\)$", "", s)          # "Document1 (2)"
    s = re.sub(r"[_\-]+(copy|kopie|final|v\d+)$", "", s)
    if len(s) < 3:
        return True
    return any(re.search(p, s) for p in rules()["generic_filename_patterns"])


# ================================================================ DATE

_MONTHS = {
    "jan": 1, "january": 1, "januar": 1, "jän": 1, "jänner": 1,
    "feb": 2, "february": 2, "februar": 2,
    "mar": 3, "march": 3, "mär": 3, "märz": 3, "maerz": 3, "mrz": 3,
    "apr": 4, "april": 4,
    "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juni": 6,
    "jul": 7, "july": 7, "juli": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12, "dez": 12, "dezember": 12,
}
_MON = "|".join(sorted((re.escape(m) for m in _MONTHS), key=len, reverse=True))
RE_ISO = re.compile(r"(?<![\d\w])((?:19|20)\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?![\d])")
RE_NUM = re.compile(r"(?<![\d\w.])(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})(?![\d])")
RE_DMY = re.compile(r"(?<![\w])(\d{1,2})(?:st|nd|rd|th)?\.?[\s\-]+(" + _MON + r")\.?[\s\-,]+((?:19|20)\d{2})(?![\d])", re.I)
RE_MONTH_YEAR = re.compile(r"(?<![\w\d])(" + _MON + r")\.?,?\s+((?:19|20)\d{2})(?![\d])", re.I)
RE_MDY = re.compile(r"(?<![\w])(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{2})(?![\d])", re.I)


def find_dates_in(text: str, date_order: str = "DMY") -> list[tuple[dt.date, int, int]]:
    """Return (date, start, end) for every valid date in text."""
    out = []
    def add(y, m, d, s, e):
        try:
            out.append((dt.date(int(y), int(m), int(d)), s, e))
        except ValueError:
            pass
    for m in RE_ISO.finditer(text):
        add(m.group(1), m.group(2), m.group(3), m.start(), m.end())
    for m in RE_NUM.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(3)), m.group(4)
        y = int(y) + 2000 if len(y) == 2 else int(y)
        if len(m.group(4)) == 2 and m.group(2) == "-":   # "12-10-26" too ambiguous with part numbers
            continue
        if a > 12:
            d_, mo = a, b
        elif b > 12:
            d_, mo = b, a
        else:
            d_, mo = (a, b) if date_order == "DMY" else (b, a)
        add(y, mo, d_, m.start(), m.end())
    for m in RE_DMY.finditer(text):
        add(m.group(3), _MONTHS[m.group(2).lower()], m.group(1), m.start(), m.end())
    for m in RE_MDY.finditer(text):
        add(m.group(3), _MONTHS[m.group(1).lower()], m.group(2), m.start(), m.end())
    return out


def find_date(ex: Extracted, ctx: dict, cfg: dict) -> Field:
    r = rules()
    today = cfg.get("today") or dt.date.today()
    good = _label_re(r["date_labels_good"])
    bad = _label_re(r["date_labels_bad"])
    header, hset, body = _lines(ex)
    cands: list[Cand] = []

    if ex.email and ex.email.get("date"):
        cands.append(Cand(ex.email["date"], 9.0, "email sent date"))
    if ctx.get("email_date"):
        try:
            cands.append(Cand(dt.date.fromisoformat(ctx["email_date"]), 5.0, "date of the email on the page"))
        except ValueError:
            pass
    if "date" in ex.direct:
        for d, _s, _e in find_dates_in(ex.direct["date"][0], cfg.get("date_order", "DMY")):
            cands.append(Cand(d, 8.0, ex.direct["date"][1]))

    seen_lines = 0
    prev = ""
    for idx, ln in enumerate(body[:3000]):
        found = find_dates_in(ln, cfg.get("date_order", "DMY"))
        for d, s, _e in found:
            before = ln[max(0, s - 45):s]
            ctx_txt = before if before.strip() else prev[-45:]
            score = 1.0
            why = "date in text"
            if bad.search(ctx_txt):
                score -= 3.5
                why = "date next to " + bad.search(ctx_txt).group(0)
            elif good.search(ctx_txt):
                score += 3.0
                why = f'labelled "{good.search(ctx_txt).group(0).strip()}"'
            if ln in hset:
                score += 1.5
                why += ", in document header"
            score += max(0.0, 0.8 - idx / 60)           # earlier = more likely the document date
            if d > today + dt.timedelta(days=45):
                score -= 2.5
            if d < today - dt.timedelta(days=365 * 15):
                score -= 2.0
            cands.append(Cand(d, score, why))
            seen_lines += 1
        prev = ln
    stem = ctx.get("_stem", "")
    for d, _s, _e in find_dates_in(stem.replace("_", " "), cfg.get("date_order", "DMY")):
        if d <= today + dt.timedelta(days=1):
            cands.append(Cand(d, 2.5, "date in the file name"))
    m = re.search(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)", stem)
    if m:
        try:
            d = dt.date(*map(int, m.groups()))
            if d <= today + dt.timedelta(days=1):
                cands.append(Cand(d, 2.5, "date in the file name"))
        except ValueError:
            pass
    for m in RE_MONTH_YEAR.finditer(ex.header[:3000]):
        y, mo = int(m.group(2)), _MONTHS[m.group(1).lower()]
        if 1995 <= y <= today.year + 1:
            cands.append(Cand(dt.date(y, mo, 1), 1.6, f'"{m.group(0)}" at the top (month only)'))
    for d, src in ex.meta_dates:
        if dt.date(1995, 1, 1) <= d <= today + dt.timedelta(days=1):
            cands.append(Cand(d, 0.9, src))

    best, ranked = _best([c for c in cands if c.score > 0])
    if not best:
        return Field(today.isoformat(), 0.55, "no date in the file, so today's date (download date)")
    runner = next((c.score for c in ranked[1:] if c.value != best.value), None)
    conf = _conf(best.score, runner, 4.5)
    if best.source in ("PDF creation date", "Word file created", "Excel file created", "file created",
                       "PowerPoint file created", "CAD file created", "photo taken", "newest file in archive"):
        conf = min(conf, 0.5)
    return Field(best.value.isoformat(), conf, best.source,
                 [c.value.isoformat() for c in ranked[1:4]])


# ================================================================ TYPE

@lru_cache(maxsize=1)
def _type_patterns():
    out = []
    for t in rules()["doc_types"]:
        pats = [(re.compile(r"(?<![\w])" + re.escape(k) + r"(?![\w])", re.I), w) for k, w in t["keywords"].items()]
        out.append((t["code"], pats))
    return out


def type_labels() -> dict:
    r = rules()
    d = {t["code"]: t["label"] for t in r["doc_types"]}
    d.update(r["extra_type_labels"])
    return d


def find_type(ex: Extracted, ctx: dict, cfg: dict, stem: str, ext: str = "") -> Field:
    from .detect import CODE_EXT
    r = rules()
    if ex.kind in ("msg", "eml"):
        return Field("MAIL", 0.95, "file is an email message")
    if ex.kind == "ipynb":
        return Field("NB", 0.95, "Jupyter notebook file")
    if ext in CODE_EXT and ex.kind in ("txt", "html", "xml", "unknown"):
        return Field("CODE", 0.92, f"{ext} source code file")
    if ex.kind in ("zip", "7z", "rar"):
        return Field("ZIP", 0.9, "archive file")
    if ex.kind in ("png", "jpg", "gif", "bmp", "tif") and re.search(r"(?i)screen\s*shot|screenshot|capture|snip", stem):
        return Field("SHOT", 0.9, "screenshot (from the file name)")

    header = ex.header
    body = ex.text[:400_000]
    title = ex.title or ""
    fname = "" if is_generic_filename(stem) else re.sub(r"[_\-.]+", " ", stem)
    hint = " ".join(filter(None, [ctx.get("link_text", ""), ctx.get("email_subject", "")]))
    scores: dict[str, float] = {}
    why: dict[str, str] = {}
    for code, pats in _type_patterns():
        s = 0.0
        best_kw, best_kw_s = "", 0.0
        for pat, w in pats:
            contrib = 0.0
            nh = len(pat.findall(header))
            nb = len(pat.findall(body))
            contrib += min(nh, 2) * w * 3
            contrib += min(nb, 3) * w
            if title and pat.search(title):
                contrib += w * 4
            if fname and pat.search(fname):
                contrib += w * 2
            if hint and pat.search(hint):
                contrib += w * 1.5
            if contrib:
                s += contrib
                if contrib > best_kw_s:
                    best_kw, best_kw_s = pat.pattern, contrib
        if s:
            scores[code] = s
            kw = re.sub(r"\(\?<!\[\\w\]\)|\(\?!\[\\w\]\)|\\", "", best_kw)
            where = "header" if re.search(best_kw, header, re.I) else ("title" if title and re.search(best_kw, title, re.I) else "text")
            why[code] = f'"{kw}" found in {where}'

    kd = r["kind_defaults"].get(ex.kind)
    if kd:
        scores[kd["code"]] = scores.get(kd["code"], 0) + kd["score"] * 3
        why.setdefault(kd["code"], f"{ex.kind.upper()} file")

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] < 5:
        if ex.kind in ("png", "jpg", "tif", "gif", "bmp") and not ex.text.strip():
            return Field("IMG", 0.6, "image without readable text")
        return Field("DOC", 0.2, "no document-type keywords found", [k for k, _ in ranked[:3]])
    top, s1 = ranked[0]
    s2 = ranked[1][1] if len(ranked) > 1 else None
    margin = 1.0 if not s2 else (s1 - s2) / s1
    conf = round(min(0.97, 0.3 + 0.4 * margin + 0.3 * min(1.0, s1 / 20)), 2)
    return Field(top, conf, why.get(top, ""), [k for k, _ in ranked[1:4]])


# ================================================================ REFERENCE

_REF_VALUE = r"([A-Z0-9][A-Z0-9\-/._]{1,39})"
_SEP = r"[\s.:#|º°\-–=]*"


@lru_cache(maxsize=1)
def _ref_patterns():
    out = {}
    for t, labels in rules()["reference_labels"].items():
        out[t] = [re.compile(r"(?<![\w])(?:" + lab + r")\.?" + _SEP + r"(?:&\s*date\s*[.:]?\s*)?" + _REF_VALUE, re.I)
                  for lab in labels]
        out[t + "#eol"] = [re.compile(r"(?<![\w])(?:" + lab + r")\.?[\s.:#|]*$", re.I) for lab in labels]
    return out


def _valid_ref(v: str) -> bool:
    v = v.strip(".-/_")
    if len(v) < 3 or not re.search(r"\d", v):
        return False
    if re.fullmatch(r"(19|20)\d{2}", v):
        return False
    if find_dates_in(v):
        return False
    if re.fullmatch(r"\d{11,}", v):            # phone / account-like
        return False
    if re.fullmatch(r"\d{1,2}", v):
        return False
    return True


STUDY_TYPES = {"ASSIGN", "LAB", "SLIDES", "NOTES", "EXAM", "SYLL", "REPORT", "BOOK", "NB", "CODE", "DOC"}
RE_ARXIV = re.compile(r"arXiv\s*:\s*(\d{4}\.\d{4,5})(v\d+)?", re.I)
RE_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>,;]{3,60})")


@lru_cache(maxsize=1)
def _seq_re():
    words = sorted(rules()["sequence_words"], key=len, reverse=True)
    return re.compile(r"(?<![\w])(" + "|".join(re.escape(w) for w in words) +
                      r")\s*[-_#:.]?\s*(?:no\.?\s*)?(\d{1,2})(?![\d.])", re.I)


def find_sequence(texts: list[tuple[str, float, str]]) -> list[Cand]:
    """'Assignment 3', 'Lab-05', 'Week 2', 'Lecture7' -> 'Assignment-3'."""
    out = []
    names = rules()["sequence_words"]
    for text, score, where in texts:
        for m in _seq_re().finditer(text or ""):
            label = names[m.group(1).lower()]
            out.append(Cand(f"{label}-{int(m.group(2))}", score, f'"{m.group(0).strip()}" in {where}'))
    return out


def find_ref(ex: Extracted, ctx: dict, cfg: dict, doc_type: str, stem: str = "") -> Field:
    pats = _ref_patterns()
    header, hset, body = _lines(ex)
    cands: list[Cand] = []
    if "ref" in ex.direct:
        cands.append(Cand(ex.direct["ref"][0].strip(), 9.0, ex.direct["ref"][1]))
    m = RE_ARXIV.search(ex.text[:60000])
    if m:
        cands.append(Cand("arXiv-" + m.group(1), 9.0 if doc_type == "PAPER" else 5.0, "arXiv identifier"))
    elif doc_type == "PAPER":
        m = RE_DOI.search(ex.text[:30000])
        if m:
            cands.append(Cand(m.group(1).rstrip(".)"), 6.0, "DOI"))
    seq_score = 7.0 if doc_type in STUDY_TYPES else 3.0
    cands += find_sequence([(ex.big_title or "", seq_score + 0.5, "the title"), (ex.title or "", seq_score, "the file properties"),
                            ("\n".join(header[:8]), seq_score - 0.5, "the top of the page"),
                            ("" if is_generic_filename(stem) and not _seq_re().search(stem) else stem.replace("_", " "), seq_score - 1, "the original file name"),
                            (ctx.get("link_text", ""), seq_score - 2, "the link text")])

    groups = [(doc_type, 5.0)] if doc_type in rules()["reference_labels"] else []
    groups += [("ANY", 2.0)]
    groups += [(t, 1.0) for t in rules()["reference_labels"] if t not in (doc_type, "ANY")]
    lines = body[:2500]
    for idx, ln in enumerate(lines):
        for t, base in groups:
            for p in pats[t]:
                for m in p.finditer(ln):
                    v = m.group(1).strip(".-/_,;:")
                    if _valid_ref(v):
                        sc = base + (2.0 if ln in hset else 0) + max(0, 0.6 - idx / 80)
                        lab = re.sub(r"\s+", " ", ln[m.start():m.start(1)]).strip(" .:#|")
                        cands.append(Cand(v, sc, f'after "{lab}"'))
            for p in pats[t + "#eol"]:
                if p.search(ln) and idx + 1 < len(lines):
                    nxt = lines[idx + 1].split("|")[0].strip()
                    tok = nxt.split()[0] if nxt.split() else ""
                    tok = tok.strip(".,;:")
                    if re.fullmatch(_REF_VALUE, tok, re.I) and _valid_ref(tok):
                        sc = base - 0.5 + (2.0 if ln in hset else 0)
                        cands.append(Cand(tok, sc, f'below "{ln.strip(" .:#|")}"'))
    best, ranked = _best(cands, key=lambda c: c.value.upper())
    if not best or best.score < 2:
        return Field(None, 0.0, "no reference / number found")
    value = best.value
    # Drawing revision
    rev = None
    if "rev" in ex.direct:
        rev = ex.direct["rev"][0]
    elif doc_type in ("DRW", "CAD", "SPEC"):
        m = re.search(r"(?<![\w])(?:rev(?:ision)?|index|änderungsindex|ai)\.?\s*[:#]?\s*([A-Z0-9]{1,3})(?![\w])", ex.text[:20000], re.I)
        if m and m.group(1).lower() not in ("no", "nr", "of"):
            rev = m.group(1)
    if rev and rev.lower() not in value.lower():
        value = f"{value} Rev{rev.upper()}"
    runner = next((c.score for c in ranked[1:]), None)
    return Field(value, _conf(best.score, runner, 7.0), best.source, [c.value for c in ranked[1:4]])


# ================================================================ PARTY (customer / supplier)

@lru_cache(maxsize=1)
def _company_re():
    suf = "|".join(rules()["legal_suffixes"])
    word = r"(?:[A-Z][\w&'.\-]*|&|and|und|of)"
    return re.compile(r"(?<![\w])((?:" + word + r"\s+){0,5}?[A-Z][\w&'.\-]*)\s*,?\s+(" + suf + r")(?![\w])")


_LEAD_NOISE = re.compile(r"^(?:(?:to|from|an|von|m/s\.?|messrs\.?|dear|customer|kunde|supplier|vendor|lieferant|bill|ship|sold|the|attn\.?|kind|for|with|by|at|our|your|ihr|ihre|firma)\s+)+", re.I)


def _strip_suffix(name: str) -> str:
    suf = "|".join(rules()["legal_suffixes"])
    s = re.sub(r"\s*,?\s+(?:" + suf + r")\s*$", "", name.strip(), flags=re.I)
    return s.strip(" ,.-")


def short_party(name: str) -> str:
    s = _strip_suffix(name)
    words = [w for w in re.split(r"\s+", s) if w and w not in ("&",)]
    words = words[:3]
    out = []
    for w in words:
        if w.isupper() and len(w) > 4:
            w = w.capitalize()
        out.append(w)
    return " ".join(out)


def _is_own(name: str, cfg: dict) -> bool:
    low = name.lower()
    return any(o and o.lower() in low for o in cfg.get("own_names", []))


def _domain_name(domain: str) -> str:
    parts = domain.lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "ac", "gov", "org", "net"):
        core = parts[-3]
    else:
        core = parts[-2] if len(parts) >= 2 else parts[0]
    return core.replace("-", " ").title()


def _type_word(s: str) -> bool:
    low = s.lower().strip()
    return any(low == k or (len(k) > 5 and k in low) for t in rules()["doc_types"] for k in t["keywords"])


RE_COURSE = re.compile(r"(?<![\w\-/])([A-Z]{2,5})\s?-?(\d{3,4}[A-Z]{0,2})(?![\w\-/])")
_COURSE_BLOCK = {"ISO", "IEEE", "ISBN", "PNR", "GST", "GSTIN", "UTR", "HSN", "PAN", "DOI", "NO", "NR", "REV", "FAT",
                 "ID", "PO", "INV", "AD", "BC", "PIN", "TEL", "FAX", "UPI", "IFSC", "AY", "FY", "SEM", "RFC", "CVE",
                 "COVID", "SDG", "IP", "TCP", "UDP", "USB", "HDMI", "RTX", "GTX", "AMD", "ARM", "DDR", "MAY", "JUN",
                 "JAN", "FEB", "MAR", "APR", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "WIN", "MS", "PS", "HW", "Q",
                 "ROOM", "LAB", "PAGE", "EXP", "CAT", "TIME", "AM", "PM", "INR", "USD", "EUR", "RS", "NH", "SH"}
RE_INSTITUTION = re.compile(
    r"((?:[A-Z][\w&.'\-]*\s+){0,4}(?:University|Institute|College|School|Academy|Polytechnic|Vidyalaya|Vishwavidyalaya)"
    r"(?:\s+(?:of|for)\s+[A-Z][\w&.'\-]*(?:\s+(?:and|&)?\s*[A-Z][\w&.'\-]*){0,3})?)")


def _norm_course(s: str) -> str:
    return re.sub(r"[\s\-]+", "", s).upper()


def _course_ok(code: str) -> bool:
    m = re.match(r"([A-Z]+)(\d+)([A-Z]*)$", code)
    if not m or m.group(1) in _COURSE_BLOCK:
        return False
    if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", code):      # PAN-number shape: never use personal IDs
        return False
    if re.fullmatch(r"(19|20)\d\d", m.group(2)) and not m.group(3):   # "SPRING 2026"
        return False
    return True


def _acronym(full: str) -> str:
    words = [w for w in re.split(r"[\s\-]+", full) if w]
    caps = [w for w in words if w[:1].isupper() and w.lower() not in ("of", "and", "for", "the")]
    if not caps:
        return full
    if caps[0].isupper() and len(caps[0]) <= 5:          # "IIT Madras" -> "IIT Madras"
        return " ".join(caps[:2])
    if len(caps) <= 2:                                     # "Stanford University" stays readable
        return " ".join(caps)
    ac = "".join(w[0] for w in caps)                      # "Vellore Institute of Technology" -> "VIT"
    return ac if 2 <= len(ac) <= 6 else " ".join(words[:3])


def _host_name(host: str) -> str:
    n = _domain_name(host)
    return n.upper() if n.isalpha() and len(n) <= 4 else n


def find_party(ex: Extracted, ctx: dict, cfg: dict, doc_type: str) -> Field:
    r = rules()
    parties = cfg.get("parties", [])
    own_domains = {d.lower() for d in cfg.get("own_domains", [])}
    free = set(r["free_email_domains"])
    header, hset, body = _lines(ex)
    text = ex.text[:300_000]
    cands: list[Cand] = []

    if "party" in ex.direct and not _is_own(ex.direct["party"][0], cfg):
        cands.append(Cand(ex.direct["party"][0], 8.0, ex.direct["party"][1]))

    # --- 1. sender email domains
    senders = []
    if ex.email and ex.email.get("from_addr"):
        senders.append((ex.email["from_addr"], 9.0, "email sender"))
    for a in ctx.get("sender_emails", [])[:5]:
        senders.append((a.lower(), 3.0, "sender shown on the web page"))  # weak hint: the document itself wins
    for addr, sc, why in senders:
        dom = addr.rsplit("@", 1)[-1] if "@" in addr else ""
        if not dom or dom in own_domains or any(dom.endswith("." + o) for o in own_domains):
            continue
        matched = False
        for p in parties:
            if any(dom == d or dom.endswith("." + d) for d in p.get("domains", [])):
                cands.append(Cand(p["display"], sc + 1, f"{why} domain @{dom} matches master data"))
                matched = True
        if not matched and dom not in free:
            cands.append(Cand(_domain_name(dom), sc - 3, f"{why} domain @{dom}"))

    # --- 2. master-data names / aliases in the text
    for p in parties:
        for alias in p.get("match_names", []):
            if len(alias) < 3:
                continue
            pat = re.compile(r"(?<![\w])" + re.escape(alias) + r"(?![\w])", re.I)
            nh = len(pat.findall(ex.header))
            nb = len(pat.findall(text))
            if nh or nb:
                sc = (7.0 if nh else 4.0) + min(1.5, 0.3 * (nb - 1))
                cands.append(Cand(p["display"], sc, f'"{alias}" found in {"header" if nh else "text"} (master data)'))
                break

    # --- 3. company names with legal suffixes (GmbH, Pvt Ltd, AG ...)
    to_re = _label_re(r["party_labels_to"])
    from_re = _label_re(r["party_labels_from"])
    letterhead = " ".join(header[:4])
    outgoing = _is_own(letterhead, cfg)
    prev = ""
    for idx, ln in enumerate(body[:1500]):
        for m in _company_re().finditer(ln):
            raw = _LEAD_NOISE.sub("", m.group(1)).strip()
            if not raw or len(raw) < 2:
                continue
            full = f"{raw} {m.group(2)}"
            if _is_own(full, cfg):
                continue
            sc = 1.0
            why = "company name in text"
            if ln in hset:
                sc += 2.5
                why = "company name in header"
                if idx < 4 and not outgoing:
                    sc += 2.0
                    why = "letterhead of the document"
            lab_ctx = ln[:m.start()] + " " + prev
            if to_re.search(lab_ctx):
                sc += 2.0 + (2.0 if outgoing else 0)
                why = f'addressee ("{to_re.search(lab_ctx).group(0)}")'
            elif from_re.search(lab_ctx):
                sc += 2.0
                why = f'sender ("{from_re.search(lab_ctx).group(0)}")'
            if ex.email and idx > 3:
                sc += 0.5   # email signatures name the sender's company
            # fuzzy match against master data
            if parties:
                try:
                    from rapidfuzz import fuzz, process
                    names = {p["display"]: p for p in parties}
                    best = process.extractOne(full, [n for p in parties for n in p.get("match_names", [])],
                                              scorer=fuzz.token_set_ratio)
                    if best and best[1] >= 88:
                        disp = next(p["display"] for p in parties if best[0] in p.get("match_names", []))
                        cands.append(Cand(disp, sc + 3.0, f'"{full}" matches master data ({int(best[1])}%)'))
                        continue
                except Exception:
                    pass
            cands.append(Cand(short_party(full), sc, f"{why}: {full}"))
        prev = ln

    # --- 4. course codes (CSE2001, CS 101, BCSE202L): the natural "source" of study material
    lab_cc = re.compile(r"(?:course|subject|paper)\s*(?:code|no\.?)\s*[:\-|]*\s*([A-Z]{2,5}\s?-?\d{2,4}[A-Z]{0,2})(?![\w])", re.I)
    for m in lab_cc.finditer(text[:60000]):
        cands.append(Cand(_norm_course(m.group(1)), 8.0, f'course code "{m.group(1)}"'))
        break
    if doc_type in STUDY_TYPES:
        for idx, ln in enumerate(header[:15] + ([ex.big_title] if ex.big_title else [])):
            for m in RE_COURSE.finditer(ln):
                code = _norm_course(m.group(0))
                if _course_ok(code):
                    cands.append(Cand(code, 4.5 - idx * 0.1, f'course code "{m.group(0)}" at the top'))
        for src, sc in ((ctx.get("link_text", ""), 3.0), ("" if is_generic_filename(ctx.get("_stem", "")) else ctx.get("_stem", ""), 3.5)):
            for m in RE_COURSE.finditer((src or "").replace("_", " ")):
                code = _norm_course(m.group(0))
                if _course_ok(code):
                    cands.append(Cand(code, sc, f'course code "{m.group(0)}" in the name'))

    # --- 5. universities / institutes -> short form (Vellore Institute of Technology -> VIT)
    for idx, ln in enumerate(body[:200]):
        for m in RE_INSTITUTION.finditer(ln):
            full = re.sub(r"\s+", " ", m.group(1)).strip()
            if _is_own(full, cfg) or len(full) < 6:
                continue
            sc = (2.5 if ln in hset else 1.0) + (1.0 if doc_type in ("CERT", "MARKS", "SYLL", "EXAM", "OFFER", "LETTER", "REPORT") else 0)
            cands.append(Cand(_acronym(full), sc, f"institution: {full}"))

    # --- 6a. who issued it: the big name at the top of receipts, tickets, certificates, bills
    titles = [t for t in (ex.big_title or "").split(" || ") if t]
    if doc_type in ("RCPT", "INV", "TICKET", "CERT", "OFFER", "STMT", "QUO") and titles:
        for t in titles[:2]:
            words = t.split()
            if words and re.fullmatch(r"[A-Z]{2,6}", words[0]) and not _type_word(words[0]):
                cands.append(Cand(words[0], 3.5, f'name at the top: "{t}"'))
                break
            if 1 <= len(words) <= 3 and not _type_word(t) and not re.search(r"\d", t):
                cands.append(Cand(t.title() if t.isupper() else t, 3.5, f'name at the top: "{t}"'))
                break
    if doc_type in ("RCPT", "INV", "TICKET", "CERT", "OFFER", "STMT") and header:
        top0 = header[0].strip()
        w0 = top0.split()
        if 1 <= len(w0) <= 3 and not re.search(r"\d", top0) and not _type_word(top0) and len(top0) <= 40:
            cands.append(Cand(top0.title() if top0.isupper() and len(top0) > 4 else top0, 4.0, f'name at the very top: "{top0}"'))
    if doc_type in ("RCPT", "INV", "TICKET"):
        m = re.search(r"(?im)^\s*(?:merchant|sold by|seller|billed by|paid to|operator|airline)\s*[:\-]\s*([A-Z][\w&.' \-]{1,40})$", text[:20000])
        if m:
            cands.append(Cand(m.group(1).strip(), 5.0, f'labelled "{m.group(0).split(":")[0].strip()}"'))
    # papers: first author's surname ("Vaswani et al")
    if doc_type == "PAPER" and titles:
        lines = header[:12]
        for i, ln in enumerate(lines):
            if titles[0][:25] in ln or ln in titles[0]:
                for nxt in lines[i + 1:i + 3]:
                    first = re.split(r",|\band\b|∗|\*|\d", nxt)[0].strip()
                    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z\-']+){1,2}", first):
                        more = len(re.findall(r",|\band\b", nxt)) > 0
                        cands.append(Cand(first.split()[-1] + (" et al" if more else ""), 4.5, f"first author: {first}"))
                        break
                break

    # --- 6. the website it came from (arxiv.org, moodle.vit.ac.in, coursera.org)
    host = (ctx.get("page_host") or "").lower()
    if host and host not in set(r["generic_hosts"]) and not any(host.endswith("." + g) for g in r["generic_hosts"]):
        cands.append(Cand(_host_name(host), 2.5, f"website: {host}"))

    # --- 7. metadata organisation
    for v, why in ((ex.company, "file properties: company"),):
        if v and not _is_own(v, cfg) and len(v) > 2:
            cands.append(Cand(short_party(v), 2.0, why))

    # map every free-text candidate onto the master-data name when it clearly matches
    if parties:
        try:
            from rapidfuzz import fuzz
            for c in cands:
                if any(c.value == p["display"] for p in parties):
                    continue
                for p in parties:
                    if any(fuzz.token_set_ratio(c.value, n) >= 90 for n in p["match_names"]):
                        c.source += " (matched to master data)"
                        c.value = p["display"]
                        c.score += 1.0
                        break
        except ImportError:
            pass

    best, ranked = _best(cands, key=lambda c: c.value.lower())
    if not best or best.score < 1.5:
        return Field(None, 0.0, "no source (course, sender, organisation) found")
    runner = next((c.score for c in ranked[1:]), None)
    return Field(best.value, _conf(best.score, runner, 8.0), best.source, [c.value for c in ranked[1:4]])


# ================================================================ SUBJECT

_ADDRESS_HINT = re.compile(r"(?i)\b(street|str\.|strasse|straße|road|rd\.|nagar|plot|sipcot|phone|tel|fax|e-?mail|www\.|gstin|vat|pin|india|germany|deutschland|p\.?o\.? box|postfach|page\s+\d|seite\s+\d)\b|@|\d{5,}")


_SMALL = {"and", "of", "the", "for", "to", "in", "on", "with", "from", "a", "an", "at", "by", "or", "vs", "via", "using"}
_UNITS = {"mm", "cm", "kg", "pcs", "nos", "mpa", "kn", "um", "µm", "mic", "pol", "ltr"}


_FILLER = {"re", "fw", "fwd", "aw", "wg", "please", "find", "attached", "attachment", "pdf", "docx", "xlsx",
           "pptx", "final", "v1", "v2", "v3", "copy", "download", "file", "document", "dear", "hello", "hi", "new",
           "updated", "kind", "reg", "ref"}


def _clean_subject(s: str, remove: list[str], phrases: list[str] = (), light: bool = False) -> str:
    """light=True for real titles: keep small words ('Attention Is All You Need'); drop only filler."""
    sw = _FILLER if light else set(rules()["subject_stopwords"])
    s = re.sub(r"^\s*((re|aw|fw|fwd|wg|antw)\s*:\s*)+", "", s, flags=re.I)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    for d, a, b in sorted(find_dates_in(s), key=lambda x: -x[1]):
        s = s[:a] + " " * (b - a) + s[b:]
    for ph in sorted(phrases, key=len, reverse=True):
        s = re.sub(r"(?<![\w])" + re.escape(ph) + r"(?![\w])", " ", s, flags=re.I)
    for r_ in remove:
        if r_:
            for tok in re.split(r"[\s_\-]+", r_):
                if len(tok) > 1:
                    s = re.sub(r"(?<![\w])" + re.escape(tok) + r"(?![\w])", " ", s, flags=re.I)
    words = re.findall(r"[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9.+/&\-]*", s)
    alpha = [w for w in words if w.isalpha()]
    shouting = alpha and sum(w.isupper() for w in alpha) / len(alpha) > 0.6
    if shouting:   # "RAVI KUMAR" -> "Ravi Kumar", keeps short acronyms (AI, ML, TCP)
        words = [w.capitalize() if w.isalpha() and w.isupper() and len(w) >= 4 else w for w in words]
    out = []
    for w in words:
        lw = w.lower().strip(".")
        if lw in sw or (len(lw) < 2 and not (light and out and lw.isalpha())):
            continue
        if re.fullmatch(r"[\d.\-/]+", w) and len(w) > 6:
            continue
        w = w.strip(".-/")
        if w[:1].islower() and len(w) >= 3 and w not in _UNITS and lw not in _SMALL:
            w = w[0].upper() + w[1:]
        elif w.isalpha() and w.isupper() and len(w) > 4:
            w = w.capitalize()
        out.append(w)
        if len(out) >= 7:
            break
    while out and out[-1].lower() in ("of", "and", "the", "a", "an", "to", "for", "in", "on", "with", "&"):
        out.pop()
    while out and out[0].lower() in ("the", "a", "an", "of", "and", "&", "to"):
        out.pop(0)
    return " ".join(out)


def _code_comment(text: str) -> str | None:
    """First meaningful line of a module docstring or top comment in a source file."""
    m = re.match(r'\s*(?:#![^\n]*\n)?(?:#[^\n]*coding[^\n]*\n)?\s*(?:"""|\'\'\'|/\*\*?)\s*([^\n]+)', text)
    if m:
        return m.group(1).strip(" *\"'")
    for ln in text.splitlines()[:15]:
        c = re.match(r"\s*(?:#|//|--|%)\s*(.+)", ln)
        if c and not re.search(r"(?i)^(!|-\*-|coding|copyright|license|author|@|=+$|-+$|\*+$|todo)", c.group(1)):
            return c.group(1).strip()
    return None


def find_subject(ex: Extracted, ctx: dict, cfg: dict, stem: str, used: list[str], doc_type: str = "") -> Field:
    r = rules()
    header, hset, body = _lines(ex)
    type_words = [k for t in r["doc_types"] for k in t["keywords"]]
    cands: list[Cand] = []
    if ex.email and ex.email.get("subject"):
        cands.append(Cand(ex.email["subject"], 8.0, "email subject"))
    if ctx.get("email_subject"):
        cands.append(Cand(ctx["email_subject"], 5.0, "subject of the email on the page"))
    if "subject" in ex.direct:
        cands.append(Cand(ex.direct["subject"][0], 8.0, ex.direct["subject"][1]))

    lab = _label_re(r["subject_labels"])
    for idx, ln in enumerate(body[:400]):
        cells = [c.strip() for c in ln.split("|")]
        nxt = body[idx + 1] if idx + 1 < len(body) else ""
        if len(cells) >= 3:
            # table header row ("Description | Qty | Rate"): take the cell below, same column
            for ci, cell in enumerate(cells):
                if lab.fullmatch(cell.strip(" .:")):
                    below = [c.strip() for c in nxt.split("|")]
                    if ci < len(below) and len(below[ci]) > 2 and not re.fullmatch(r"[\d.,\s]+", below[ci]):
                        cands.append(Cand(below[ci][:120], 4.5, f'first row under column "{cell}"'))
                    break
            continue
        m = lab.match(ln)
        if m and re.match(r"\s*\.?\s*(?:[:|\-–]|$)", ln[m.end():]):   # "Subject:" not "Material Test ..."
            rest = ln[m.end():].strip(" .:#|-–")
            if not rest:
                rest = nxt.split("|")[0].strip()
            if rest and len(rest) > 2:
                cands.append(Cand(rest[:120], 6.0 if ln in hset else 3.5, f'labelled "{m.group(0)}"'))
    if ex.title and not is_generic_filename(ex.title) and not re.match(r"(?i)microsoft (word|excel|powerpoint)", ex.title):
        cands.append(Cand(ex.title, 4.5 if doc_type == "NB" else 4.0, "document title in file properties" if doc_type != "NB" else "first heading in the notebook"))
    big = 6.5 if doc_type in ("PAPER", "SLIDES", "REPORT", "BOOK", "ASSIGN", "LAB", "NOTES", "CERT", "SYLL", "EXAM", "GUIDE") else 5.0
    for i, t in enumerate([t for t in (ex.big_title or "").split(" || ") if t]):
        if is_generic_filename(t) or RE_INSTITUTION.search(t.title()) or _company_re().search(t):
            continue
        cands.append(Cand(t, big - 1.2 * i, "title (largest text on page 1)" if i == 0 else "heading on page 1"))
    top = ex.text[:20000]
    m = re.search(r"(?i)(?:course|paper|subject)\s*(?:title|name)\s*[:\-]\s*([^|\n]{3,90}?)(?:\s{3,}|\||$)", top, re.M)
    if m:
        cands.append(Cand(m.group(1).strip(), 6.0, "course title"))
    if doc_type == "CERT":
        m = re.search(r"(?is)(?:successfully\s+completed|completion\s+of|for\s+completing|participated\s+in|in\s+recognition\s+of)\s*(?:the\s+)?(?:course\s+)?([^\n]*)\n?([^\n]*)", top)
        if m:
            val = m.group(1).strip(" :.") or m.group(2).strip(" :.")
            if val:
                cands.append(Cand(val[:100], 7.5, "what the certificate is for"))
    if doc_type == "TICKET":
        m = re.search(r"(?i)\bfrom\s*:?\s*(?:[A-Z]{2,5}\s+)?([A-Za-z][A-Za-z .]{2,30}?)\s+to\s*:?\s*(?:[A-Z]{2,5}\s+)?([A-Za-z][A-Za-z .]{2,30}?)(?:\s{2,}|\||$|\n)", top, re.M)
        if m:
            cands.append(Cand(f"{m.group(1).strip()} to {m.group(2).strip()}", 7.0, "journey (from / to)"))
    if doc_type == "CODE":
        c = _code_comment(ex.text[:5000])
        if c:
            cands.append(Cand(c, 3.0, "first comment in the code"))
    if not is_generic_filename(stem):
        cands.append(Cand(re.sub(r"[_]+", " ", stem), 3.5, "original file name"))
    lt = ctx.get("link_text", "")
    if lt and not is_generic_filename(os.path.splitext(lt)[0]):
        cands.append(Cand(os.path.splitext(lt)[0], 2.5, "link text on the web page"))

    # first title-like line in the header
    for ln in header[:10]:
        if _ADDRESS_HINT.search(ln) or _company_re().search(ln) or find_dates_in(ln):
            continue
        words = ln.split()
        if 2 <= len(words) <= 9 and sum(c.isalpha() for c in ln) / max(1, len(ln)) > 0.6:
            low = ln.lower()
            if any(low.strip(" :") == k for k in type_words):
                continue
            cands.append(Cand(ln, 2.0, "title line in document header"))
            break

    # drop document-type words that are titles on their own ("Quotation", "Rechnung") and labels
    phrases = [k for k in type_words if " " in k or len(k) > 5] + ["no", "nr", "number", "date", "datum"]
    cleaned = []
    loose = ("original file name", "link text", "title line")
    for c in cands:
        v = _clean_subject(str(c.value), used, phrases, light=not any(x in c.source for x in loose))
        if v and len(v) >= 3:
            cleaned.append(Cand(v, c.score, c.source))
    best, ranked = _best(cleaned, key=lambda c: c.value.lower())
    if not best:
        return Field(None, 0.0, "no subject found")
    runner = next((c.score for c in ranked[1:]), None)
    return Field(best.value, _conf(best.score, runner, 6.0), best.source, [c.value for c in ranked[1:4]])
