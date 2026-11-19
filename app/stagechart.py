"""Stage Chart: turn a worship chord chart PDF into a stage chart PDF.

Rules (from the STAGE CHART project):
  * light mode, two columns, 17pt lyrics
  * keep the original's key (never transpose) and aim for its page count
  * repeated back-to-back sections are shown once with "×2"
  * bridges and other repeats that are not back-to-back are printed in order, with their cues
  * slash chords are written properly (D/F#)
  * the source PDF is only ever read, never written

Usage:  python3 stagechart.py chart.pdf [more.pdf ...] [--out DIR]
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------------------------
# Chord vocabulary
# --------------------------------------------------------------------------------------------
NOTE = r"[A-G](?:#|b|♯|♭)?"
CHORD_RE = re.compile(
    r"^\(?" + NOTE +
    r"(?:maj|Maj|ma|M|min|mi|m|dim|°|aug|\+|ø|-)?"
    r"(?:\d+|sus\d*|add\d+|maj\d*|M\d+|[b#♯♭]\d+|\([^)]*\)|alt|no\d+|\+|/(?=\d)\d+)*"
    r"(?:/" + NOTE + r")?\)?\*?$"
)
CHORD_EXTRA = re.compile(r"^(\|+|\|\||\|\|:|:\|\||/|%|-|–|\.|x\d+|\(x\d+\)|\d+x|\(\d+x\)|N\.?C\.?|\(N\.?C\.?\)|"
                         r"\(|\)|\[|\]|:)$", re.I)
ACCIDENTAL_CHARS = {"#": "#", "♯": "#", "b": "b", "♭": "b"}

SECTION_NAMES = (r"intro|verse|pre[- ]?chorus|prechorus|chorus|post[- ]?chorus|bridge|tag|turnaround|"
                 r"ending|end|outro|interlude|instrumental|inst|vamp|refrain|breakdown|channel|hook|solo|"
                 r"coda|reprise|spontaneous|exhortation|link|rap|misc|turn|ad lib|free worship")
SECTION_RE = re.compile(
    r"^(?:(?P<badge>[A-Z][A-Za-z]?\d?[a-z]?)\s+)?"
    r"(?P<name>(?:" + SECTION_NAMES + r"))"
    r"(?P<num>\s*\d+[a-zA-Z]?)?"
    r"\s*[:.]?"
    r"(?P<rep>\s*[\(\[]?\s*(?:x\s*\d+|\d+\s*x|×\s*\d+|repeat)\s*[\)\]]?)?"
    r"(?P<rest>\s*[\(\[].*[\)\]])?\s*$",
    re.I,
)

JUNK_RE = re.compile(
    r"(page\s*:?\s*\d+\s*(/|of)\s*\d+|multitracks\.com|a product of|for use solely|songselect|"
    r"terms of use|planningcenter|planning center|www\.|https?://|ccli|license\s*#|"
    r"all rights reserved|chart by|mtid)", re.I)
CREDIT_RE = re.compile(r"(©|℗|copyright|writers?\s*:|words and music|written by|ccli song)", re.I)

MAJOR_SCALES = {}
_SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_PC = {n: i for i, n in enumerate(_SHARP_NAMES)}
_PC.update({n: i for i, n in enumerate(_FLAT_NAMES)})
FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb", "Dm", "Gm", "Cm", "Fm", "Bbm", "Ebm"}


def key_scale(key: str) -> set[str] | None:
    """Spelled note names of the key's scale (major, or natural minor for "Em" etc.)."""
    m = re.match(r"^([A-G](?:#|b)?)(m|min)?$", key or "")
    if not m:
        return None
    root, minor = m.group(1), bool(m.group(2))
    if root not in _PC:
        return None
    steps = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    flat = (root + ("m" if minor else "")) in FLAT_KEYS or root.endswith("b")
    letters = "CDEFGAB"
    start = letters.index(root[0])
    out = set()
    for i, st in enumerate(steps):
        pc = (_PC[root] + st) % 12
        letter = letters[(start + i) % 7]
        nat = _PC[letter]
        diff = (pc - nat) % 12
        acc = {0: "", 1: "#", 11: "b", 2: "##", 10: "bb"}[diff]
        out.add(letter + acc)
    _ = flat
    return out


def key_accidental(key: str) -> str:
    sc = key_scale(key) or set()
    if any(n.endswith("b") for n in sc):
        return "b"
    return "#"


# --------------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------------
@dataclass
class Char:
    t: str
    x0: float
    x1: float
    base: float      # baseline, measured from the top of the page (bigger = lower)
    size: float
    font: str
    color: tuple


@dataclass
class Word:
    chars: list

    @property
    def t(self):
        return "".join(c.t for c in self.chars)

    @property
    def x0(self):
        return self.chars[0].x0

    @property
    def x1(self):
        return self.chars[-1].x1

    @property
    def base(self):
        return max(c.base for c in self.chars)

    @property
    def size(self):
        return max(c.size for c in self.chars)


@dataclass
class Row:
    words: list

    @property
    def text(self):
        return " ".join(w.t for w in self.words)

    @property
    def base(self):
        return Counter(round(w.base, 1) for w in self.words).most_common(1)[0][0]

    @property
    def size(self):
        return max(w.size for w in self.words)

    @property
    def x0(self):
        return min(w.x0 for w in self.words)

    @property
    def x1(self):
        return max(w.x1 for w in self.words)

    def style(self):
        cs = [c for w in self.words for c in w.chars if c.t.strip()]
        if not cs:
            return ("", 0, ())
        f = Counter(c.font for c in cs).most_common(1)[0][0]
        s = Counter(round(c.size) for c in cs).most_common(1)[0][0]
        col = Counter(c.color for c in cs).most_common(1)[0][0]
        return (f, s, col)


@dataclass
class Section:
    label: str
    kind: str                       # one letter: I V P C B T X E R O
    cues: list = field(default_factory=list)
    lines: list = field(default_factory=list)   # chordpro strings, or ("cue", text)
    times: int = 1
    cue_by_pass: list = field(default_factory=list)

    def body_key(self):
        return tuple(l if isinstance(l, str) else ("cue",) for l in self.lines)


@dataclass
class Song:
    title: str = ""
    subtitle: str = ""
    key: str = ""
    bpm: str = ""
    time: str = ""
    credits: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    source_pages: int = 1
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------------------------
# PDF text extraction (pdfminer.six)
# --------------------------------------------------------------------------------------------
def extract_chars(path):
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LTChar, LTContainer
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    rm = PDFResourceManager()
    dev = PDFPageAggregator(rm, laparams=None)
    it = PDFPageInterpreter(rm, dev)
    pages = []
    with open(path, "rb") as fh:          # read-only: the source is never modified
        for page in PDFPage.get_pages(fh):
            it.process_page(page)
            lay = dev.get_result()
            h = lay.height
            out = []

            def walk(o):
                for x in o:
                    if isinstance(x, LTChar):
                        t = x.get_text()
                        if t.startswith("(cid:"):
                            t = "�"
                        try:
                            col = tuple(round(float(v), 2) for v in (x.graphicstate.ncolor or ()))  # type: ignore
                        except Exception:
                            col = ()
                        if len(col) == 1:
                            col = (col[0],) * 3
                        size = x.size or abs(x.matrix[3])
                        out.append(Char(t, x.x0, x.x1, h - x.matrix[5], size, x.fontname, col))
                    elif isinstance(x, LTContainer):
                        walk(x)

            walk(lay)
            pages.append((lay.width, h, out))
    return pages


def build_rows(chars):
    """Group characters into rows, then rows into words."""
    rows = []
    for c in sorted(chars, key=lambda c: (c.base, c.x0)):
        if not c.t:
            continue
        for r in reversed(rows[-6:]):
            ref = r[0]
            if abs(ref.base - c.base) < 0.3 * max(ref.size, c.size):
                r.append(c)
                break
        else:
            rows.append([c])
    # superscripts (smaller, raised) belong to the row just below them: G⁷, D⁷ˢᵘˢ, Bb²⁽⁶⁾
    rows.sort(key=lambda r: min(c.base for c in r))
    merged = []
    for r in rows:
        merged.append(r)
    i = 0
    while i < len(merged) - 1:
        r, nxt = merged[i], merged[i + 1]
        rs = max(c.size for c in r)
        ns = max(c.size for c in nxt)
        rb = Counter(round(c.base) for c in r).most_common(1)[0][0]
        nb = Counter(round(c.base) for c in nxt).most_common(1)[0][0]
        txt = "".join(c.t for c in sorted(r, key=lambda c: c.x0)).strip()
        if rs < 0.85 * ns and 0 < nb - rb < 0.75 * ns and re.fullmatch(r"[0-9susadmj()#b♯♭+°/\s\-]+", txt or "x"):
            nxt.extend(r)
            merged.pop(i)
            continue
        i += 1
    out = []
    for r in merged:
        r.sort(key=lambda c: c.x0)
        words, cur = [], []
        for c in r:
            if c.t.isspace():
                if cur:
                    words.append(Word(cur))
                    cur = []
                continue
            if cur:
                gap = c.x0 - cur[-1].x1
                sz = max(c.size, cur[-1].size)
                if gap > 0.2 * sz:
                    words.append(Word(cur))
                    cur = []
            cur.append(c)
        if cur:
            words.append(Word(cur))
        if words:
            out.append(Row(words))
    return out


def split_columns(width, height, rows):
    """Find a vertical gutter near the middle; return (full_rows_top, [col rows...], full_rows_bottom)."""
    words = [(w, r) for r in rows for w in r.words]
    if len(words) < 20:
        return [rows]
    best = None
    for x in range(int(width * 0.3), int(width * 0.7), 2):
        cross = sum(1 for w, _ in words if w.x0 < x < w.x1)
        left = sum(1 for w, _ in words if w.x1 <= x)
        right = sum(1 for w, _ in words if w.x0 >= x)
        if left < 0.2 * len(words) or right < 0.2 * len(words):
            continue
        if best is None or cross < best[0] or (cross == best[0] and abs(x - width / 2) < abs(best[1] - width / 2)):
            best = (cross, x)
    if best is None:
        return [rows]
    cross, gx = best
    crossing_rows = [r for r in rows if any(w.x0 < gx < w.x1 for w in r.words)]
    # crossing rows must be header/footer material, never body lines
    body = [r for r in rows if r not in crossing_rows]
    if not body:
        return [rows]
    if len(crossing_rows) > max(3, 0.12 * len(rows)):
        return [rows]
    top_cut = min(r.base for r in body)
    bot_cut = max(r.base for r in body)
    mid_crossers = [r for r in crossing_rows if top_cut < r.base < bot_cut]
    if mid_crossers:
        # a crossing row in the middle of the body: only allowed if it sits above everything in
        # at least one column (a header that spans the page)
        return [rows]
    left = Row  # noqa
    lcol, rcol = [], []
    for r in body:
        lw = [w for w in r.words if w.x1 <= gx]
        rw = [w for w in r.words if w.x0 >= gx]
        if lw:
            lcol.append(Row(lw))
        if rw:
            rcol.append(Row(rw))
    top = [r for r in crossing_rows if r.base <= top_cut]
    bottom = [r for r in crossing_rows if r.base >= bot_cut]
    return [top + lcol, rcol + bottom] if rcol else [rows]


# --------------------------------------------------------------------------------------------
# Line classification
# --------------------------------------------------------------------------------------------
def clean_token(t):
    return t.replace("♯", "#").replace("♭", "b").strip(",;")


def is_chord_token(t):
    t = clean_token(t)
    t = t.replace("�", "#")
    return bool(CHORD_RE.match(t)) or bool(CHORD_EXTRA.match(t))


def is_chord_row(row):
    toks = [w.t for w in row.words]
    real = [t for t in toks if CHORD_RE.match(clean_token(t).replace("�", "#"))]
    if not real:
        return False
    return all(is_chord_token(t) for t in toks)


def section_match(text):
    t = text.strip()
    m = SECTION_RE.match(t)
    if not m:
        return None
    if t == t.lower():
        return None
    return m


def kind_of(name):
    n = name.lower()
    if n.startswith("pre"):
        return "P"
    if n.startswith("post"):
        return "C"
    for k, letter in (("intro", "I"), ("verse", "V"), ("chorus", "C"), ("refrain", "R"), ("bridge", "B"),
                      ("tag", "T"), ("vamp", "T"), ("outro", "O"), ("ending", "E"), ("end", "E"),
                      ("coda", "E"), ("hook", "C"), ("channel", "B")):
        if n.startswith(k):
            return letter
    return "X"


def fix_chord(tok, key, notes, evidence=False):
    """Normalise a chord: ♯/♭ to #/b, restore dropped accidentals, spell slash basses in the key."""
    t = clean_token(tok)
    acc = key_accidental(key)
    if "�" in t:
        # an unknown glyph straight after a note letter is a sharp or flat the PDF didn't map
        t = re.sub(r"([A-G])�", lambda m: m.group(1) + acc, t)
        t = t.replace("�", "")
    if evidence:
        t = re.sub(r"^(\(?)([A-G])(?![#b])", lambda m: m.group(1) + m.group(2) + acc, t)
    m = re.match(r"^(.*)/([A-G])([#b]?)(\)?)$", t)
    sc = key_scale(key)
    if m and sc and not m.group(3):
        letter = m.group(2)
        if letter not in sc and (letter + acc) in sc:
            new = f"{m.group(1)}/{letter}{acc}{m.group(4)}"
            notes.add(f"{t} → {new}")
            t = new
    return t


def chord_word_tokens(row, key, notes):
    """Chord tokens of a chord row, with dropped-glyph detection (a gap inside a chord)."""
    out = []
    ws = row.words
    i = 0
    while i < len(ws):
        w = ws[i]
        t = w.t
        x0, x1 = w.x0, w.x1
        evidence = False
        # "B" + gap + "sus2": a dropped ♭/♯ left a small hole inside the chord
        while i + 1 < len(ws):
            nx = ws[i + 1]
            gap = nx.x0 - x1
            if re.fullmatch(r"\(?[A-G]", t) and re.match(r"^(sus|maj|add|m(?!aj)|min|dim|aug|[0-9]|/)", nx.t) \
                    and gap < 0.65 * w.size:
                t += nx.t
                x1 = nx.x1
                evidence = True
                i += 1
                continue
            if re.search(r"/$", t) and gap < 0.65 * w.size and re.match(r"^[A-G]", nx.t):
                t += nx.t
                x1 = nx.x1
                i += 1
                continue
            break
        # the inner gap after the root letter inside one word also counts as evidence
        cs = w.chars
        if len(cs) >= 2 and re.match(r"[A-G]", cs[0].t) and cs[1].x0 - cs[0].x1 > 0.18 * w.size \
                and cs[1].t not in "#b♯♭/":
            evidence = True
        if CHORD_RE.match(clean_token(t).replace("�", "#")):
            out.append((x0, fix_chord(t, key, notes, evidence)))
        else:
            out.append((x0, clean_token(t)))
        i += 1
    return out


def place_chords(chords, lyric, snap):
    """Merge a chord row onto the lyric row below it as a ChordPro line."""
    text, xs = "", []
    for w in lyric.words:
        if text:
            text += " "
            xs.append(None)
        for c in w.chars:
            text += c.t
            xs.append(c.x0)
    # x position of every character (spaces take the next character's x)
    pos = []
    for i, x in enumerate(xs):
        if x is None:
            nxt = next((y for y in xs[i + 1:] if y is not None), None)
            pos.append((nxt or 0) - 0.5)
        else:
            pos.append(x)
    end_x = lyric.x1
    ins, trailing = [], []
    for cx, ct in chords:
        if not CHORD_RE.match(ct) and not CHORD_EXTRA.match(ct):
            trailing.append(ct)
            continue
        if cx > end_x + 1:
            trailing.append(ct)
            continue
        idx = 0
        for i, p in enumerate(pos):
            if p <= cx + 1.2:
                idx = i
            else:
                break
        if text[idx] == " ":
            idx += 1
        # word bounds around idx
        ws = text.rfind(" ", 0, idx) + 1
        we = text.find(" ", idx)
        we = len(text) if we < 0 else we
        word = text[ws:we]
        core = len(word.rstrip(",.!?'’\")"))
        if snap and core >= 2 and idx - ws >= core - 1:
            idx = we          # drawn just right of the syllable: falls after the word
        elif idx - ws <= 1 and (snap or idx - ws == 0 or core <= 3):
            idx = ws
        ins.append((idx, ct))
    mid = [(i, t) for i, t in ins if i < len(text)]
    end = [t for i, t in ins if i >= len(text)] + trailing
    for n, (idx, t) in sorted(enumerate(mid), key=lambda p: (p[1][0], p[0]), reverse=True):
        if idx > 0 and text[idx - 1] != " " and (idx >= len(text) or text[idx] == " "):
            text = text[:idx] + f" [{t}]" + text[idx:]
        else:
            text = text[:idx] + f"[{t}]" + text[idx:]
    for t in end:
        text += f" [{t}]"
    return re.sub(r"\s+", " ", text).strip()


def chords_only_line(tokens):
    parts = []
    for _, t in tokens:
        if CHORD_RE.match(t):
            parts.append(f"[{t}]")
        else:
            parts.append(t)
    return " ".join(parts)


# --------------------------------------------------------------------------------------------
# Parsing a whole chart
# --------------------------------------------------------------------------------------------
META_RES = {
    "key": re.compile(r"\bkey\s*(?:of|[:\-–=])?\s*([A-G](?:#|b|♯|♭)?m?)(?![a-z])", re.I),
    "bpm": re.compile(r"\b(?:tempo|bpm)\s*[:\-–=]?\s*(\d{2,3}(?:\.\d+)?)", re.I),
    "bpm2": re.compile(r"\b(\d{2,3})\s*bpm\b", re.I),
    "time": re.compile(r"\btime(?:\s*sig(?:nature)?)?\s*[:\-–=]?\s*(\d{1,2}/\d{1,2})", re.I),
}


def parse(path):
    pages = extract_chars(path)
    song = Song(source_pages=len(pages))
    notes = set()
    all_text = []
    page_rows = []
    for pi, (w, h, chars) in enumerate(pages):
        rows = build_rows(chars)
        page_rows.append((w, h, rows))
        all_text += [r.text for r in rows]
    first_rows = page_rows[0][2] if page_rows else []
    if not any(rows for _, _, rows in page_rows):
        raise ValueError("This PDF has no readable text. It may be a scanned image, which the app can't read.")

    joined = "\n".join(all_text)
    # ---- metadata
    m = META_RES["key"].search(joined)
    song.key = m.group(1).replace("♯", "#").replace("♭", "b") if m else ""
    if not song.key:
        fm = re.search(r"[._ -]([A-G](?:#|b)?m?)\.pdf$", os.path.basename(path))
        if fm:
            song.key = fm.group(1)
    m = META_RES["bpm"].search(joined) or META_RES["bpm2"].search(joined)
    song.bpm = m.group(1) if m else ""
    m = META_RES["time"].search(joined)
    song.time = m.group(1) if m else ""

    # title = biggest text on page 1, subtitle = the next row under it
    if first_rows:
        big = max(first_rows, key=lambda r: (r.size, -r.base))
        title_words = [w for w in big.words if w.size >= big.size * 0.9]
        song.title = " ".join(w.t for w in title_words).strip()
        song.title = re.split(r"\s{2,}|\s+Page\s*:", song.title)[0].strip()
        below = [r for r in first_rows if r.base > big.base and r.base < big.base + 4 * big.size]
        for r in below:
            t = r.text
            t = META_RES["key"].sub("", t)
            t = re.sub(r"(tempo|bpm|time)\s*[:\-–=]?\s*[\d/.]+", "", t, flags=re.I)
            t = re.sub(r"\s*[|·]\s*$", "", t).strip(" |-–·")
            if t and not section_match(t) and not JUNK_RE.search(t) and not is_chord_row(r) \
                    and len(t) < 80 and not re.fullmatch(r"(\S{1,3}\s+){3,}\S{1,3}", t):
                song.subtitle = t
                break
    if not song.title:
        song.title = os.path.splitext(os.path.basename(path))[0]

    # ---- body
    title_norm = song.title.lower()

    def is_header_row(r):
        t = r.text.strip()
        tl = t.lower()
        if tl == title_norm or (title_norm and tl.startswith(title_norm) and len(tl) < len(title_norm) + 25
                                and not section_match(t)):
            return True
        if song.subtitle and t.startswith(song.subtitle) and not section_match(t):
            return True
        if META_RES["key"].search(t) and (META_RES["bpm"].search(t) or META_RES["time"].search(t)):
            return True
        if re.fullmatch(r"(?:key|tempo|time|bpm)\b.*", t, re.I) and len(t) < 30:
            return True
        # MultiTracks roadmap: a row of short section codes ("I V1 C It V2 C ...")
        if re.fullmatch(r"(?:[A-Z][A-Za-z]?\d?[a-z]?\s+){3,}[A-Z][A-Za-z]?\d?[a-z]?", t) and not is_chord_row(r):
            return True
        return False

    body = []
    for pi, (w, h, rows) in enumerate(page_rows):
        rows = [r for r in rows if not is_header_row(r)]
        cols = split_columns(w, h, rows)
        for col in cols:
            # the column's left edge: where most lines start
            starts = Counter(round(r.x0 / 4) * 4 for r in col if not JUNK_RE.search(r.text))
            left = starts.most_common(1)[0][0] if starts else 0
            for r in col:
                r.left = left
            for r in (sorted(col, key=lambda r: r.base) if len(cols) == 1 else col):
                t = r.text.strip()
                if not t or is_header_row(r):
                    continue
                if CREDIT_RE.search(t):
                    c = re.sub(r"\s+", " ", t)
                    if c not in song.credits and not re.search(r"for use solely|terms of use", c, re.I):
                        song.credits.append(c)
                    continue
                if JUNK_RE.search(t):
                    continue
                body.append(r)

    snap = bool(re.search(r"multitracks", joined, re.I))

    # lyric style: the most common style of rows that sit right under a chord row
    styles = Counter()
    for a, b in zip(body, body[1:]):
        if is_chord_row(a) and not is_chord_row(b) and not section_match(b.text):
            styles[b.style()[:2]] += len(b.text)
    lyric_style = styles.most_common(1)[0][0] if styles else None
    lyric_colors = Counter()
    for a, b in zip(body, body[1:]):
        if is_chord_row(a) and not is_chord_row(b):
            lyric_colors[b.style()[2]] += 1
    lyric_color = lyric_colors.most_common(1)[0][0] if lyric_colors else None

    sections = []
    cur = None

    def new_section(label, kind):
        nonlocal cur
        cur = Section(label=label, kind=kind)
        sections.append(cur)

    i = 0
    while i < len(body):
        r = body[i]
        t = r.text.strip()
        sm = section_match(t)
        if sm and not is_chord_row(r):
            name = sm.group("name").upper()
            name = {"PRECHORUS": "PRE-CHORUS", "PRE CHORUS": "PRE-CHORUS", "INST": "INSTRUMENTAL"}.get(name, name)
            num = (sm.group("num") or "").strip()
            label = f"{name} {num}".strip()
            new_section(label, kind_of(name))
            rep = sm.group("rep")
            if rep:
                n = re.search(r"\d+", rep)
                if n:
                    cur.times = int(n.group())
                elif "repeat" in rep.lower():
                    cur.times = 2
            if sm.group("rest"):
                cur.cues.append(sm.group("rest").strip(" ()[]"))
            i += 1
            continue
        if cur is None:
            new_section("INTRO" if is_chord_row(r) else "", "I" if is_chord_row(r) else "X")
        if is_chord_row(r):
            toks = chord_word_tokens(r, song.key, notes)
            nxt = body[i + 1] if i + 1 < len(body) else None
            if nxt is not None and not is_chord_row(nxt) and not section_match(nxt.text) \
                    and _is_lyric(nxt, lyric_style, lyric_color) \
                    and 0 < nxt.base - r.base < 3.2 * r.size:
                cur.lines.append(place_chords(toks, nxt, snap))
                i += 2
                continue
            cur.lines.append(chords_only_line(toks))
            i += 1
            continue
        # plain text: lyric without chords, or a performance cue
        indented = r.x0 - getattr(r, "left", r.x0) > 40
        if _is_lyric(r, lyric_style, lyric_color) and not indented:
            cur.lines.append(re.sub(r"\s+", " ", t))
        else:
            cue = re.sub(r"\s+", " ", t)
            if cur.lines:
                cur.lines.append(("cue", cue))
            else:
                cur.cues.append(cue)
        i += 1

    sections = [s for s in sections if s.lines or s.cues]
    # a leading untitled block made only of cues belongs to the first real section
    if sections and not sections[0].label and not sections[0].lines and len(sections) > 1:
        sections[1].cues = sections[0].cues + sections[1].cues
        sections.pop(0)
    for s in sections:
        if not s.label:
            s.label = "INTRO" if s is sections[0] else "INSTRUMENTAL"
        s.cue_by_pass = [" · ".join(s.cues)] if s.cues else [""]
    song.sections = merge_repeats(sections)
    song.notes = sorted(notes)
    return song


def _is_lyric(row, lyric_style, lyric_color):
    if lyric_style is None:
        return True
    f, s, col = row.style()
    if lyric_color is not None and col != lyric_color and col and lyric_color:
        return False
    if (f, s) == lyric_style:
        return True
    lf, ls = lyric_style
    if f != lf:
        # italic/bold variants of the lyric font are cues; another family is a cue
        return False
    return abs(s - ls) <= 1


def merge_repeats(sections):
    """Back-to-back sections with identical chords and lyrics are shown once, ×N."""
    out = []
    for s in sections:
        if out and out[-1].body_key() == s.body_key() and out[-1].label == s.label \
                and any(isinstance(l, str) for l in s.lines):
            prev = out[-1]
            prev.times += s.times
            prev.cue_by_pass += s.cue_by_pass
            continue
        out.append(s)
    for s in out:
        passes = s.cue_by_pass
        if s.times > 1 and len(passes) > 1 and len(set(passes)) > 1:
            ords = ["1st", "2nd", "3rd"] + [f"{n}th" for n in range(4, 20)]
            s.cues = [f"{ords[k]}: {p}" for k, p in enumerate(passes) if p]
        elif passes and passes[0]:
            s.cues = [passes[0]]
        else:
            s.cues = []
    # number sections that come back later: CHORUS 1, 2, 3; a numbered one repeats as "BRIDGE 1 · 2nd time"
    labels = Counter(s.label for s in out)
    numbered_names = {s.label.split()[0] for s in out if re.search(r"\d", s.label)}
    count = Counter()
    for s in out:
        if not s.label:
            continue
        name = s.label
        if re.search(r"\d", name) or name in ("INTRO", "OUTRO", "ENDING", "END"):
            continue
        if name in numbered_names:
            s.label = f"{name} 1"            # BRIDGE next to BRIDGE 2 is BRIDGE 1
        elif labels[name] > 1:
            count[name] += 1
            s.label = f"{name} {count[name]}"
    seen = Counter()
    first_body = {}
    for s in out:
        k = s.label
        if k in first_body and first_body[k] == s.body_key():
            seen[k] += 1
            ords = {2: "2nd", 3: "3rd"}
            s.label = f"{k} · {ords.get(seen[k] + 1, str(seen[k] + 1) + 'th')} time"
        elif k not in first_body:
            first_body[k] = s.body_key()
    return out


# --------------------------------------------------------------------------------------------
# Rendering (reportlab)
# --------------------------------------------------------------------------------------------
LIGHT = dict(
    bg=(1, 1, 1), lyric=(0.07, 0.07, 0.07), chord=(0.62, 0.05, 0.08), cue=(0.08, 0.30, 0.70),
    muted=(0.42, 0.42, 0.42), rule=(0.80, 0.80, 0.80), badge_text=(1, 1, 1),
    badges={"I": (0.38, 0.38, 0.42), "V": (0.16, 0.42, 0.72), "P": (0.50, 0.33, 0.70), "C": (0.78, 0.22, 0.20),
            "B": (0.85, 0.50, 0.08), "T": (0.20, 0.55, 0.45), "R": (0.10, 0.55, 0.62), "X": (0.38, 0.38, 0.42),
            "E": (0.25, 0.25, 0.25), "O": (0.25, 0.25, 0.25)},
)

_fonts_ready = False


def register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fd = os.path.join(HERE, "fonts")
    pdfmetrics.registerFont(TTFont("Sans", os.path.join(fd, "Carlito-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("SansB", os.path.join(fd, "Carlito-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("SansI", os.path.join(fd, "Carlito-Italic.ttf")))
    pdfmetrics.registerFont(TTFont("SansBI", os.path.join(fd, "Carlito-BoldItalic.ttf")))
    _fonts_ready = True


def sw(text, font, size):
    from reportlab.pdfbase import pdfmetrics
    return pdfmetrics.stringWidth(text, font, size)


def parse_line(line):
    """ChordPro line -> list of (chord or None, text)."""
    segs = []
    pos = 0
    for m in re.finditer(r"\[([^\]]*)\]", line):
        if m.start() > pos or not segs:
            pre = line[pos:m.start()]
            if segs:
                segs[-1] = (segs[-1][0], segs[-1][1] + pre)
            elif pre:
                segs.append((None, pre))
        segs.append((m.group(1), ""))
        pos = m.end()
    rest = line[pos:]
    if segs:
        segs[-1] = (segs[-1][0], segs[-1][1] + rest)
    else:
        segs.append((None, rest))
    return segs


def pretty_chord(c):
    return c.replace("♯", "#").replace("♭", "b")


@dataclass
class Layout:
    size: float = 17.0
    margin: float = 30.0
    gutter: float = 20.0
    line_gap: float = 1.0       # extra space between lines (× size)
    sec_gap: float = 0.75       # space between sections (× size)
    page_w: float = 612.0
    page_h: float = 792.0


def measure_line(segs, L):
    """Lay out one chord/lyric line. Returns list of placed items and total width, has_chords, has_lyrics."""
    cs = L.size * 0.92
    x = 0.0
    placed = []
    has_ch = any(c for c, _ in segs)
    has_ly = any(re.search(r"[A-Za-z0-9]", t) for _, t in segs)
    chord_end = -1e9
    for k, (c, t) in enumerate(segs):
        if c:
            label = pretty_chord(c)
            if x < chord_end:
                # push the lyric along so chords don't collide; mark the stretched word
                pad = chord_end - x
                prev_text = placed[-1][2] if placed else ""
                inword = bool(prev_text) and not prev_text.endswith(" ") and t[:1].strip() != ""
                placed.append(("pad", x, "-" if inword and has_ly else "", pad))
                x = chord_end
            cw = sw(label, "SansB", cs)
            placed.append(("chord", x, label, cw))
            chord_end = x + cw + L.size * 0.45
        if t:
            tw = sw(t, "Sans", L.size)
            placed.append(("text", x, t, tw))
            x += tw
    width = max(x, chord_end - L.size * 0.45)
    return placed, width, has_ch, has_ly


CONT_INDENT = 12.0


def wrap_line(line, L, maxw):
    """Split a ChordPro line so it fits the column width."""
    segs = parse_line(line)
    _, width, _, _ = measure_line(segs, L)
    if width <= maxw:
        return [segs]
    # break into word units keeping chords attached
    units = []
    for c, t in segs:
        parts = re.split(r"(?<= )", t) if t else [""]
        for j, p in enumerate(parts):
            units.append((c if j == 0 else None, p))
    def ok_break(j):
        return j > 0 and (units[j][0] or units[j - 1][1].endswith(" "))

    # two lines if possible, split where both halves are closest in width
    best = None
    for j in range(1, len(units)):
        if not ok_break(j):
            continue
        w1 = measure_line(units[:j], L)[1]
        w2 = measure_line(units[j:], L)[1] + CONT_INDENT
        if w1 <= maxw and w2 <= maxw:
            score = max(w1, w2)
            if best is None or score < best[0]:
                best = (score, j)
    if best:
        lines = [units[:best[1]], units[best[1]:]]
    else:
        lines, cur = [], []
        for j, u in enumerate(units):
            trial = cur + [u]
            if cur and measure_line(trial, L)[1] > maxw - (CONT_INDENT if lines else 0) and ok_break(j):
                lines.append(cur)
                cur = [u]
            else:
                cur = trial
        if cur:
            lines.append(cur)
    out = []
    for ln in lines:
        merged = []
        for c, t in ln:
            if merged and c is None:
                merged[-1] = (merged[-1][0], merged[-1][1] + t)
            else:
                merged.append((c, t))
        out.append(merged)
    return out


def block_for(section, L, colw):
    """Measure a section: list of drawable rows with heights."""
    rows = []
    for ln in section.lines:
        if isinstance(ln, tuple):
            rows.append(("cue", ln[1], L.size * 0.82 * 1.25))
            continue
        for n, segs in enumerate(wrap_line(ln, L, colw - 4)):
            if n:
                segs = [(c, t.lstrip() if k == 0 else t) for k, (c, t) in enumerate(segs)]
            placed, w, hc, hl = measure_line(segs, L)
            if n:
                placed = [(k, x + CONT_INDENT, t, ww) for k, x, t, ww in placed]
            h = 0.0
            if hc:
                h += L.size * 0.92 * 1.08
            if hl:
                h += L.size * (1.12 + 0.0)
            h += L.size * 0.18 * L.line_gap
            rows.append(("line", (placed, hc, hl), h))
    head_h = L.size * 1.55
    cue_rows = []
    for cue in section.cues:
        for part in cue.split("\n"):
            cue_rows.append(part)
    return head_h, cue_rows, rows


def wrap_text(text, font, size, maxw):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if sw(t, font, size) > maxw and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines or [""]


def roadmap(sections):
    short = {"INTRO": "Intro", "VERSE": "V", "PRE-CHORUS": "Pre", "CHORUS": "Ch", "BRIDGE": "Br", "TAG": "Tag",
             "INTERLUDE": "Int", "INSTRUMENTAL": "Inst", "OUTRO": "Outro", "ENDING": "End", "END": "End",
             "REFRAIN": "Rf", "VAMP": "Vamp", "TURNAROUND": "Turn", "BREAKDOWN": "Bkdn", "POST-CHORUS": "Post",
             "TURN": "Turn", "SOLO": "Solo", "CODA": "Coda"}
    out = []
    for s in sections:
        base = s.label.split(" · ")[0]
        parts = base.split()
        name = parts[0] if parts else ""
        num = parts[1] if len(parts) > 1 and re.match(r"\d", parts[1]) else ""
        ab = short.get(name, name.title())
        if num:
            ab = f"{ab}{num}" if len(ab) <= 2 else f"{ab} {num}"
        if s.times > 1:
            ab += f" ×{s.times}"
        if out and out[-1] == ab and s.times == 1:
            continue
        out.append(ab)
    return out


def render(song, out_path, L, theme=LIGHT, dry=False):
    """Draw the chart. Returns the number of pages."""
    register_fonts()
    from reportlab.pdfgen import canvas as rl_canvas

    W, H, M = L.page_w, L.page_h, L.margin
    colw = (W - 2 * M - L.gutter) / 2
    cv = None if dry else rl_canvas.Canvas(out_path, pagesize=(W, H))
    if cv:
        cv.setTitle(f"{song.title} - Stage Chart")
        cv.setAuthor("Stage Chart")

    # ---------- header measurements
    rm = roadmap(song.sections)
    rm_size = 12.5
    rm_rows = []
    cur, x = [], 0.0
    for i, r in enumerate(rm):
        piece = r + ("  ›  " if i < len(rm) - 1 else "")
        w = sw(piece, "SansB", rm_size)
        if cur and x + w > W - 2 * M:
            rm_rows.append(cur)
            cur, x = [], 0.0
        cur.append(piece)
        x += w
    if cur:
        rm_rows.append(cur)
    header_h = 30 + 18 + (rm_size * 1.35) * max(1, len(rm_rows)) + 10
    footer_h = 22

    pages = []          # each page: list of (col, y, item)

    def body_top(pi):
        return H - M - (header_h if pi == 0 else 26)

    bottom = M + footer_h

    # ---------- place sections into columns
    placements = []     # (page, col, y_top, section, rows_subset, cont)
    pi, col = 0, 0
    y = body_top(0)

    def next_col():
        nonlocal pi, col, y
        col += 1
        if col > 1:
            col = 0
            pi += 1
        y = body_top(pi)

    for s in song.sections:
        head_h, cue_rows, rows = block_for(s, L, colw)
        cue_lines = []
        for c in cue_rows:
            cue_lines += wrap_text(c, "SansI", L.size * 0.8, colw - 4)
        cue_h = len(cue_lines) * L.size * 0.8 * 1.2
        total = head_h + cue_h + sum(r[2] for r in rows)
        avail = y - bottom
        full = body_top(pi) - bottom
        if total > avail and y < body_top(pi) - 1:
            # does not fit here: start a fresh column if it would fit there (or if this column is mostly used)
            if total <= body_top(pi + (1 if col == 1 else 0)) - bottom or avail < 0.35 * full:
                next_col()
        # place, splitting if needed
        first = True
        remaining = list(rows)
        while True:
            hh = head_h + (cue_h if first else 0)
            avail = y - bottom
            fit, used = [], hh
            for r in remaining:
                if used + r[2] > avail and fit:
                    break
                fit.append(r)
                used += r[2]
            if not fit and remaining:
                next_col()
                continue
            placements.append((pi, col, y, s, fit, not first, cue_lines if first else []))
            y -= used + L.size * L.sec_gap
            remaining = remaining[len(fit):]
            if not remaining:
                break
            first = False
            next_col()
    npages = pi + 1
    if dry or cv is None:
        return npages

    # ---------- draw
    def draw_page_chrome(p):
        cv.setFillColorRGB(*theme["bg"])
        cv.rect(0, 0, W, H, stroke=0, fill=1)
        if p == 0:
            ty = H - M - 22
            # title, shrinking if it would run into the key box
            meta = []
            if song.key:
                meta.append(("KEY", song.key))
            if song.bpm:
                meta.append(("BPM", song.bpm))
            if song.time:
                meta.append(("TIME", song.time))
            box_w = 0
            for lab, val in meta:
                box_w += max(sw(val, "SansB", 20), sw(lab, "SansB", 8)) + 22
            ts = 26
            while ts > 14 and sw(song.title, "SansB", ts) > W - 2 * M - box_w - 12:
                ts -= 0.5
            cv.setFillColorRGB(*theme["lyric"])
            cv.setFont("SansB", ts)
            cv.drawString(M, ty, song.title)
            if song.subtitle:
                ss = 13
                while ss > 8 and sw(song.subtitle, "Sans", ss) > W - 2 * M - box_w - 12:
                    ss -= 0.5
                cv.setFillColorRGB(*theme["muted"])
                cv.setFont("Sans", ss)
                cv.drawString(M, ty - 18, song.subtitle)
            bx = W - M
            for lab, val in reversed(meta):
                bw = max(sw(val, "SansB", 20), sw(lab, "SansB", 8)) + 14
                bx -= bw
                cv.setStrokeColorRGB(*theme["rule"])
                cv.setLineWidth(1)
                cv.roundRect(bx, ty - 16, bw, 40, 5, stroke=1, fill=0)
                cv.setFillColorRGB(*theme["muted"])
                cv.setFont("SansB", 8)
                cv.drawCentredString(bx + bw / 2, ty + 13, lab)
                cv.setFillColorRGB(*(theme["chord"] if lab == "KEY" else theme["lyric"]))
                cv.setFont("SansB", 20)
                cv.drawCentredString(bx + bw / 2, ty - 9, val)
                bx -= 8
            ry = ty - 18 - 22
            cv.setFont("SansB", rm_size)
            for rr in rm_rows:
                rx = M
                for piece in rr:
                    cv.setFillColorRGB(*theme["lyric"])
                    if "›" in piece:
                        a, b = piece.split("›")
                        cv.drawString(rx, ry, a)
                        rx2 = rx + sw(a, "SansB", rm_size)
                        cv.setFillColorRGB(*theme["muted"])
                        cv.drawString(rx2, ry, "›" + b)
                    else:
                        cv.drawString(rx, ry, piece)
                    rx += sw(piece, "SansB", rm_size)
                ry -= rm_size * 1.35
            cv.setStrokeColorRGB(*theme["rule"])
            cv.setLineWidth(0.8)
            cv.line(M, ry + rm_size * 1.35 - 7, W - M, ry + rm_size * 1.35 - 7)
        else:
            cv.setFillColorRGB(*theme["muted"])
            cv.setFont("SansB", 11)
            top = f"{song.title}" + (f"  ·  Key {song.key}" if song.key else "")
            cv.drawString(M, H - M - 8, top)
            cv.setStrokeColorRGB(*theme["rule"])
            cv.setLineWidth(0.8)
            cv.line(M, H - M - 14, W - M, H - M - 14)
        # footer
        cv.setFillColorRGB(*theme["muted"])
        cv.setFont("Sans", 7.5)
        foot = "  ·  ".join(song.credits)
        fl = wrap_text(foot, "Sans", 7.5, W - 2 * M - 60) if foot else []
        fy = M - 4
        for line in reversed(fl[:2]):
            cv.drawString(M, fy, line)
            fy += 9
        cv.setFont("SansB", 9)
        cv.drawRightString(W - M, M - 4, f"{p + 1} / {npages}")

    by_page = {}
    for pl in placements:
        by_page.setdefault(pl[0], []).append(pl)
    for p in range(npages):
        draw_page_chrome(p)
        for (_, col, ytop, s, rows, cont, cue_lines) in by_page.get(p, []):
            x0 = M + col * (colw + L.gutter)
            y = ytop
            # section header: badge + label (+ ×N)
            bs = L.size * 0.78
            label = s.label + (f"  ×{s.times}" if s.times > 1 else "") + ("  (cont.)" if cont else "")
            badge = s.kind
            bw = sw(badge, "SansB", bs) + 10
            base = y - L.size * 1.05
            cv.setFillColorRGB(*theme["badges"].get(s.kind, theme["badges"]["X"]))
            cv.roundRect(x0, base - 4, bw, bs + 8, 3, stroke=0, fill=1)
            cv.setFillColorRGB(*theme["badge_text"])
            cv.setFont("SansB", bs)
            cv.drawCentredString(x0 + bw / 2, base, badge)
            cv.setFillColorRGB(*theme["lyric"])
            ls = L.size * 0.9
            while ls > 10 and sw(label, "SansB", ls) > colw - bw - 8:
                ls -= 0.5
            cv.setFont("SansB", ls)
            cv.drawString(x0 + bw + 7, base, label)
            y -= L.size * 1.55
            if cue_lines:
                cv.setFillColorRGB(*theme["cue"])
                cv.setFont("SansI", L.size * 0.8)
                for cl in cue_lines:
                    cv.drawString(x0 + 2, y - L.size * 0.8, cl)
                    y -= L.size * 0.8 * 1.2
            for kind, data, h in rows:
                if kind == "cue":
                    cv.setFillColorRGB(*theme["cue"])
                    cv.setFont("SansI", L.size * 0.82)
                    cv.drawString(x0 + 2, y - L.size * 0.82, data)
                    y -= h
                    continue
                placed, hc, hl = data
                cy = y - L.size * 0.92 if hc else None
                ly = (y - (L.size * 0.92 * 1.08 if hc else 0) - L.size * 0.95) if hl else None
                for it in placed:
                    k, x, t, w = it
                    if k == "chord":
                        cv.setFillColorRGB(*theme["chord"])
                        cv.setFont("SansB", L.size * 0.92)
                        cv.drawString(x0 + 2 + x, cy, t)
                    elif k == "text" and ly is not None:
                        cv.setFillColorRGB(*theme["lyric"])
                        cv.setFont("Sans", L.size)
                        cv.drawString(x0 + 2 + x, ly, t)
                    elif k == "text" and ly is None and t.strip():
                        # text on a chord-only line (bar marks etc.)
                        cv.setFillColorRGB(*theme["muted"])
                        cv.setFont("SansB", L.size * 0.92)
                        cv.drawString(x0 + 2 + x, cy, t)
                    elif k == "pad" and t and ly is not None:
                        cv.setFillColorRGB(*theme["muted"])
                        cv.setFont("Sans", L.size)
                        cv.drawCentredString(x0 + 2 + x + w / 2, ly, t)
                y -= h
        cv.showPage()
    cv.save()
    return npages


def plan_layout(song):
    """Pick the layout: 17pt two columns, tightened spacing if that saves pages, to match the original."""
    target = song.source_pages
    tries = [
        Layout(),
        Layout(line_gap=0.6, sec_gap=0.55),
        Layout(line_gap=0.4, sec_gap=0.45, margin=26, gutter=16),
        Layout(line_gap=0.2, sec_gap=0.35, margin=24, gutter=14),
    ]
    best = None
    for L in tries:
        n = render(song, None, L, dry=True)
        if best is None or n < best[0]:
            best = (n, L)
        if n <= target:
            return L, n
    return best[1], best[0]


def safe_name(s):
    s = re.sub(r"[\\/:*?\"<>|]+", "-", s).strip(" .")
    return s or "Chart"


def convert(src, out_dir=None):
    """Convert one chart. Returns (output_path, summary_lines)."""
    src = os.path.abspath(src)
    song = parse(src)
    if not any(isinstance(l, str) for s in song.sections for l in s.lines):
        raise ValueError("Couldn't find any chords or lyrics in this PDF.")
    L, n = plan_layout(song)
    out_dir = out_dir or os.path.dirname(src)
    name = f"{safe_name(song.title)} - Stage Chart" + (f" - {safe_name(song.key)}" if song.key else "") + " (Light).pdf"
    out = os.path.join(out_dir, name)
    if os.path.abspath(out) == src:
        out = out[:-4] + " (new).pdf"
    tmp = out + ".part"
    render(song, tmp, L)
    os.replace(tmp, out)
    summary = [f"{song.title}: key {song.key or '?'}, {n} page{'s' if n != 1 else ''} "
               f"(original {song.source_pages})"]
    if n > song.source_pages:
        summary.append("One page longer than the original even with tighter spacing.")
    merged = [s for s in song.sections if s.times > 1]
    if merged:
        summary.append("Shown once with ×N: " + ", ".join(f"{s.label} ×{s.times}" for s in merged))
    if song.notes:
        summary.append("Slash chords spelled in the key: " + ", ".join(song.notes))
    if not song.key:
        summary.append("No key found on the chart.")
    return out, summary


def main(argv):
    out_dir = None
    files = []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out_dir = next(it)
        elif a == "--dump":
            os.environ["STAGECHART_DUMP"] = "1"
        else:
            files.append(a)
    if not files:
        print(__doc__)
        return 2
    rc = 0
    for f in files:
        try:
            if os.environ.get("STAGECHART_DUMP"):
                song = parse(f)
                print(f"# {song.title} | {song.subtitle} | key={song.key} bpm={song.bpm} time={song.time} "
                      f"pages={song.source_pages}")
                for c in song.credits:
                    print("# credit:", c)
                for s in song.sections:
                    print(f"\n== {s.kind} {s.label}" + (f" ×{s.times}" if s.times > 1 else "") +
                          (f"   [{' | '.join(s.cues)}]" if s.cues else ""))
                    for l in s.lines:
                        print("  " + (l if isinstance(l, str) else f"({l[1]})"))
                continue
            out, summary = convert(f, out_dir)
            print("OK\t" + out)
            for s in summary:
                print("  " + s)
        except Exception as e:      # report and carry on with the next file
            rc = 1
            print(f"FAIL\t{f}\t{e}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
