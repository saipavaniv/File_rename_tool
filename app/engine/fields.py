"""Find the five naming fields in an extracted document.

Every field is chosen by scoring candidates with transparent rules:
  * where it was found (title/header beats body text),
  * what label sits next to it ("Invoice No:", "Datum:", "Customer:"),
  * whether it matches Kramski's own master data (customers/suppliers),
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
    for d, src in ex.meta_dates:
        if dt.date(1995, 1, 1) <= d <= today + dt.timedelta(days=1):
            cands.append(Cand(d, 0.9, src))

    best, ranked = _best([c for c in cands if c.score > 0])
    if not best:
        return Field(today.isoformat(), 0.15, "no date found; today's date used")
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


def find_type(ex: Extracted, ctx: dict, cfg: dict, stem: str) -> Field:
    r = rules()
    if ex.kind in ("msg", "eml"):
        return Field("MAIL", 0.95, "file is an email message")

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


def find_ref(ex: Extracted, ctx: dict, cfg: dict, doc_type: str) -> Field:
    pats = _ref_patterns()
    header, hset, body = _lines(ex)
    cands: list[Cand] = []
    if "ref" in ex.direct:
        cands.append(Cand(ex.direct["ref"][0].strip(), 9.0, ex.direct["ref"][1]))

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
        return Field(None, 0.0, "no reference number found")
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

    # --- 4. metadata organisation
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
        return Field(None, 0.0, "no customer or supplier identified")
    runner = next((c.score for c in ranked[1:]), None)
    return Field(best.value, _conf(best.score, runner, 8.0), best.source, [c.value for c in ranked[1:4]])


# ================================================================ SUBJECT

_ADDRESS_HINT = re.compile(r"(?i)\b(street|str\.|strasse|straße|road|rd\.|nagar|plot|sipcot|phone|tel|fax|e-?mail|www\.|gstin|vat|pin|india|germany|deutschland|p\.?o\.? box|postfach|page\s+\d|seite\s+\d)\b|@|\d{5,}")


_UNITS = {"mm", "cm", "kg", "pcs", "nos", "mpa", "kn", "um", "µm", "mic", "pol", "ltr"}


def _clean_subject(s: str, remove: list[str], phrases: list[str] = ()) -> str:
    sw = set(rules()["subject_stopwords"])
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
    out = []
    for w in words:
        lw = w.lower().strip(".")
        if lw in sw or len(lw) < 2:
            continue
        if re.fullmatch(r"[\d.\-/]+", w) and len(w) > 6:
            continue
        w = w.strip(".-/")
        if w.isalpha() and w.islower() and len(w) >= 3 and w not in _UNITS:
            w = w.capitalize()
        elif w.isalpha() and w.isupper() and len(w) > 4:
            w = w.capitalize()
        out.append(w)
        if len(out) >= 5:
            break
    return " ".join(out)


def find_subject(ex: Extracted, ctx: dict, cfg: dict, stem: str, used: list[str]) -> Field:
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
        cands.append(Cand(ex.title, 4.0, "document title in file properties"))
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
    for c in cands:
        v = _clean_subject(str(c.value), used, phrases)
        if v and len(v) >= 3:
            cleaned.append(Cand(v, c.score, c.source))
    best, ranked = _best(cleaned, key=lambda c: c.value.lower())
    if not best:
        return Field(None, 0.0, "no subject found")
    runner = next((c.score for c in ranked[1:]), None)
    return Field(best.value, _conf(best.score, runner, 6.0), best.source, [c.value for c in ranked[1:4]])
