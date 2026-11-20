"""Planning Center Services, read only, with a personal access token.

Only Matt uses this, so it signs in with a personal access token (an Application ID and a Secret made at
https://api.planningcenteronline.com/oauth/applications) sent as HTTP Basic auth. Nothing here changes
anything in Planning Center: it reads service types, plans and songs, and downloads chart PDFs.

    client = Client(app_id, secret)
    client.check()                                   # raises AuthError if the token is wrong
    types = client.service_types()                   # [ServiceType]
    plans = client.plans_between(types, date(2026, 11, 1), date(2026, 12, 1))
    songs = client.songs(plan)                       # [SongItem], in service order, with the plan's key
    pick  = client.best_chart(song)                  # Attachment or None (prefers a chart in the plan's key)
    client.download(pick, "/path/file.pdf")
"""
from __future__ import annotations

import base64
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime

API = "https://api.planningcenteronline.com/services/v2"
TOKEN_PAGE = "https://api.planningcenteronline.com/oauth/applications"
USER_AGENT = "StageChart (desktop app)"


class PCOError(Exception):
    """Something went wrong talking to Planning Center. str(e) is a sentence for the window."""


class AuthError(PCOError):
    pass


@dataclass
class ServiceType:
    id: str
    name: str


@dataclass
class Plan:
    id: str
    service_type: ServiceType
    day: date | None
    dates: str                  # Planning Center's own wording, e.g. "November 22, 2026"
    title: str = ""
    series: str = ""
    items_count: int = 0

    @property
    def name(self):
        """What to call the plan in the window: its title, else its series, else the service type."""
        return self.title or self.series or self.service_type.name


@dataclass
class Attachment:
    id: str
    filename: str
    content_type: str
    url: str                    # the attachment's own API link; downloads go through url + "/open"
    level: str                  # "key" (attached to the song's key) or "arrangement"
    key_name: str = ""          # for level "key": that key's name, e.g. "D"

    @property
    def is_pdf(self):
        return "pdf" in (self.content_type or "").lower() or self.filename.lower().endswith(".pdf")


@dataclass
class SongItem:
    id: str
    sequence: int
    title: str
    key_name: str               # the key the song is scheduled in on this plan, e.g. "D" ("" if none)
    song_id: str | None
    arrangement_id: str | None
    key_id: str | None
    attachments: list = field(default_factory=list)


# --------------------------------------------------------------------------------------------
# Keys: compare the plan's key with the chart's key without caring about spelling (C# = Db)
# --------------------------------------------------------------------------------------------
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def key_root(name: str):
    """'D' -> (2, False), 'Ebm' -> (3, True), 'F#min' -> (6, True). None if it doesn't look like a key."""
    m = re.match(r"^\s*([A-Ga-g])\s*(#|♯|b|♭)?\s*(m(?:in(?:or)?)?|maj(?:or)?)?(?![A-Za-z])", name or "")
    if not m:
        return None
    pc = _PC[m.group(1).upper()]
    if m.group(2) in ("#", "♯"):
        pc += 1
    elif m.group(2) in ("b", "♭"):
        pc -= 1
    minor = bool(m.group(3)) and m.group(3).lower().startswith("m") and not m.group(3).lower().startswith("maj")
    return pc % 12, minor


def same_key(a: str, b: str) -> bool:
    ka, kb = key_root(a), key_root(b)
    return ka is not None and ka == kb


def _key_in_filename(filename: str, key: str) -> bool:
    """True when a file name says the key, like 'Song - D.pdf', 'Song (Eb).pdf', 'Song_in_F#.pdf', 'Song.D.pdf'."""
    if not key:
        return False
    stem = os.path.splitext(filename)[0]
    tokens = re.split(r"[\s_\-().,\[\]]+", stem)
    want = key_root(key)
    tokens = [t for t in tokens if t]
    for i, t in enumerate(tokens):
        if i >= len(tokens) - 3 and re.fullmatch(r"[A-G](#|b|♯|♭)?(m|min)?", t) and key_root(t) == want:
            return True
        if t.lower() == "key" and i + 1 < len(tokens) and key_root(tokens[i + 1]) == want:
            return True
    return False


_GOOD = ("chord", "chart")
_BAD = ("lead", "lyric", "vocal", "number", "nashville", "nns", "capo", "drum", "bass", "harmony", "choir",
        "sheet music", "piano", "score", "click", "patch")


def score_chart(att: Attachment, plan_key: str) -> int:
    """Higher is a better chord chart for this plan. Charts never get transposed, so the key matters most."""
    if not att.is_pdf:
        return -10_000
    name = att.filename.lower()
    s = 0
    if att.level == "key":
        s += 60
        if plan_key and same_key(att.key_name, plan_key):
            s += 60
    if plan_key and _key_in_filename(att.filename, plan_key):
        s += 100
    s += sum(25 for w in _GOOD if w in name)
    s -= sum(40 for w in _BAD if w in name)
    return s


def pick_chart(attachments, plan_key: str):
    pdfs = [a for a in attachments if a.is_pdf]
    if not pdfs:
        return None
    return max(pdfs, key=lambda a: (score_chart(a, plan_key), a.level == "key", -len(a.filename)))


def parse_day(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


# --------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------
def _ssl_context():
    try:
        import certifi            # the Mac app bundles certifi; Windows uses the system store
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class Client:
    def __init__(self, app_id: str, secret: str, opener=None, sleep=time.sleep):
        self.app_id = (app_id or "").strip()
        self.secret = (secret or "").strip()
        self._auth = "Basic " + base64.b64encode(f"{self.app_id}:{self.secret}".encode()).decode()
        self._open = opener or self._urlopen
        self._sleep = sleep
        self._ctx = None

    # -- low level -------------------------------------------------------------------------
    def _urlopen(self, req, timeout):
        if self._ctx is None:
            self._ctx = _ssl_context()
        return urllib.request.urlopen(req, timeout=timeout, context=self._ctx)

    def _request(self, url, method="GET", auth=True, timeout=30):
        for attempt in range(4):
            req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
            req.add_header("User-Agent", USER_AGENT)
            if auth:
                req.add_header("Authorization", self._auth)
                req.add_header("Accept", "application/json")
            try:
                with self._open(req, timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:             # rate limit: 100 requests per 20 seconds
                    wait = e.headers.get("Retry-After") if e.headers else None
                    self._sleep(min(float(wait or 5), 30))
                    continue
                if e.code == 401:
                    raise AuthError("Planning Center didn't accept the token. Check the Application ID "
                                    "and Secret.") from e
                if e.code == 403:
                    raise AuthError("This token doesn't have access to Planning Center Services.") from e
                if e.code == 404:
                    raise PCOError("Planning Center couldn't find that item. It may have been removed.") from e
                raise PCOError(f"Planning Center answered with an error ({e.code}). Try again in a "
                               "minute.") from e
            except (urllib.error.URLError, OSError) as e:
                if attempt < 2:
                    self._sleep(1.5 * (attempt + 1))
                    continue
                raise PCOError("Couldn't reach Planning Center. Check the internet connection.") from e
        raise PCOError("Planning Center is busy. Try again in a minute.")

    def get(self, path, **params):
        url = path if path.startswith("http") else API + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return json.loads(self._request(url) or b"{}")

    def get_all(self, path, limit=500, stop=None, **params):
        """Follow 'next' links. Returns (data, included). stop(item) -> True ends early."""
        params.setdefault("per_page", 100)
        out, included = [], []
        doc = self.get(path, **params)
        while True:
            for d in doc.get("data") or []:
                if stop and stop(d):
                    return out, included
                out.append(d)
            included += doc.get("included") or []
            nxt = (doc.get("links") or {}).get("next")
            if not nxt or len(out) >= limit:
                return out, included
            doc = self.get(nxt)

    # -- what the app uses -------------------------------------------------------------------
    def check(self):
        """Raises AuthError if the token is wrong. Returns the organization's name."""
        doc = self.get("")
        return ((doc.get("data") or {}).get("attributes") or {}).get("name", "")

    def service_types(self):
        data, _ = self.get_all("/service_types", order="sequence")
        return [ServiceType(d["id"], (d.get("attributes") or {}).get("name") or "Services") for d in data]

    def _plan(self, d, st):
        a = d.get("attributes") or {}
        return Plan(id=d["id"], service_type=st, day=parse_day(a.get("sort_date")), dates=a.get("dates") or "",
                    title=a.get("title") or "", series=a.get("series_title") or "",
                    items_count=a.get("items_count") or 0)

    def plans_between(self, service_types, start: date, end: date):
        """Plans with a date from start up to (not including) end, across the service types, by date."""
        out = []
        after = start.fromordinal(start.toordinal() - 1).isoformat()

        for st in service_types:
            def past_end(d):
                day = parse_day((d.get("attributes") or {}).get("sort_date"))
                return day is not None and day >= end
            data, _ = self.get_all(f"/service_types/{st.id}/plans", stop=past_end, filter="after", after=after,
                                   order="sort_date")
            for d in data:
                p = self._plan(d, st)
                if p.day and start <= p.day < end:
                    out.append(p)
        out.sort(key=lambda p: (p.day, p.service_type.name))
        return out

    def next_plan(self, service_types, today: date | None = None):
        """The soonest plan from today on, across the service types (None if there isn't one)."""
        today = today or date.today()
        best = None
        for st in service_types:
            data, _ = self.get_all(f"/service_types/{st.id}/plans", limit=5, filter="future", order="sort_date",
                                   per_page=5)
            for d in data:
                p = self._plan(d, st)
                if p.day and p.day >= today:
                    if best is None or p.day < best.day:
                        best = p
                    break
        return best

    def songs(self, plan: Plan):
        """The plan's songs in service order, each with the key it's scheduled in."""
        data, _ = self.get_all(f"/service_types/{plan.service_type.id}/plans/{plan.id}/items",
                               include="song,arrangement,key")
        out = []
        for d in data:
            a = d.get("attributes") or {}
            if a.get("item_type") != "song":
                continue
            rel = d.get("relationships") or {}

            def rid(name):
                x = (rel.get(name) or {}).get("data")
                return x.get("id") if isinstance(x, dict) else None
            out.append(SongItem(id=d["id"], sequence=a.get("sequence") or len(out), title=a.get("title") or "Song",
                                key_name=(a.get("key_name") or "").strip(), song_id=rid("song"),
                                arrangement_id=rid("arrangement"), key_id=rid("key")))
        out.sort(key=lambda s: s.sequence)
        return out

    def attachments(self, song: SongItem):
        """PDF and other files on the song's arrangement and on the key it's scheduled in."""
        if not (song.song_id and song.arrangement_id):
            return []
        base = f"/songs/{song.song_id}/arrangements/{song.arrangement_id}"
        found = []
        keys = {}
        if song.key_id:
            try:
                k = self.get(f"{base}/keys/{song.key_id}").get("data") or {}
                ka = k.get("attributes") or {}
                keys[song.key_id] = ka.get("name") or ka.get("starting_key") or ""
            except PCOError:
                pass
            try:
                data, _ = self.get_all(f"{base}/keys/{song.key_id}/attachments")
                found += [self._attachment(d, "key", keys.get(song.key_id, "")) for d in data]
            except PCOError:
                pass
        data, _ = self.get_all(f"{base}/attachments")
        found += [self._attachment(d, "arrangement") for d in data]
        seen, out = set(), []
        for a in found:
            if a.id not in seen:
                seen.add(a.id)
                out.append(a)
        song.attachments = out
        return out

    def _attachment(self, d, level, key_name=""):
        a = d.get("attributes") or {}
        url = (d.get("links") or {}).get("self") or f"{API}/attachments/{d['id']}"
        return Attachment(id=d["id"], filename=a.get("filename") or a.get("display_name") or "chart.pdf",
                          content_type=a.get("content_type") or "", url=url, level=level, key_name=key_name)

    def best_chart(self, song: SongItem):
        if not song.attachments:
            self.attachments(song)
        return pick_chart(song.attachments, song.key_name)

    def download(self, att: Attachment, dest: str):
        """Saves the file at dest (written to dest + '.part' first). Returns dest."""
        doc = json.loads(self._request(att.url.rstrip("/") + "/open", method="POST") or b"{}")
        link = ((doc.get("data") or {}).get("attributes") or {}).get("attachment_url")
        if not link:
            raise PCOError(f"Planning Center didn't give a download link for {att.filename}.")
        body = self._request(link, auth=False, timeout=120)
        if not body.startswith(b"%PDF"):
            raise PCOError(f"{att.filename} didn't download as a PDF.")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest + ".part", "wb") as fh:
            fh.write(body)
        os.replace(dest + ".part", dest)
        return dest


def safe_name(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "-", s or "").strip(" .")
    return s[:80] or "Untitled"


def plan_label(plan: Plan) -> str:
    """e.g. "2026-11-22 Sunday Morning - Advent" (the plan's title or series, when it has one)."""
    day = plan.day.isoformat() if plan.day else "no date"
    extra = plan.title or plan.series
    return f"{day} {plan.service_type.name}" + (f" - {extra}" if extra and extra != plan.service_type.name else "")


def plan_folder(base: str, plan: Plan) -> str:
    """e.g. <base>/2026-11-22 Sunday Morning - Advent"""
    return os.path.join(base, safe_name(plan_label(plan)))
