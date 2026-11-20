"""A stand-in for Planning Center, for tests and screenshots: answers the same API calls pco.Client makes.

    client = pco.Client("id", "secret", opener=FakePCO(chart_pdf).open)
"""
import io
import json
import re
import urllib.error
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

API = "https://api.planningcenteronline.com/services/v2"


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _sundays(n, start=None):
    d = start or date.today()
    d += timedelta(days=(6 - d.weekday()) % 7)
    return [d + timedelta(days=7 * i) for i in range(n)]


class FakePCO:
    def __init__(self, chart_pdf, today=None, app_id="id", secret="secret"):
        self.pdf = open(chart_pdf, "rb").read()
        self.calls = []
        self.app_id, self.secret = app_id, secret
        days = _sundays(5, today)
        self.types = [{"id": "11", "attributes": {"name": "Sunday Morning", "sequence": 1}},
                      {"id": "12", "attributes": {"name": "Youth", "sequence": 2}}]
        self.plans = {"11": [], "12": []}
        for i, d in enumerate(days):
            self.plans["11"].append({"id": str(100 + i), "type": "Plan", "attributes": {
                "sort_date": d.isoformat() + "T09:00:00Z", "dates": f"{d:%B} {d.day}, {d.year}", "title": "", "series_title": "Advent" if i < 2 else "", "items_count": 9}})
        wed = days[0] + timedelta(days=3)
        self.plans["12"].append({"id": "200", "type": "Plan", "attributes": {
            "sort_date": wed.isoformat() + "T19:00:00Z", "dates": "", "title": "Youth Night", "series_title": "",
            "items_count": 4}})
        songs = [("God of the Test", "D", True), ("Come Thou Fount", "E", True), ("Welcome", None, False),
                 ("Be Thou My Vision", "D", False), ("Amazing Grace", "G", True)]
        self.items = []
        for i, (title, key, has_key) in enumerate(songs):
            if key is None:
                self.items.append({"id": f"9{i}", "attributes": {"item_type": "item", "title": title, "sequence": i}})
                continue
            self.items.append({"id": f"9{i}", "attributes": {"item_type": "song", "title": title, "key_name": key,
                                                             "sequence": i},
                               "relationships": {"song": {"data": {"id": f"5{i}"}},
                                                 "arrangement": {"data": {"id": f"6{i}"}},
                                                 "key": {"data": {"id": f"7{i}"} if has_key else None}}})

    def _check_auth(self, req):
        import base64
        want = "Basic " + base64.b64encode(f"{self.app_id}:{self.secret}".encode()).decode()
        if req.get_header("Authorization") != want:
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    def open(self, req, timeout=30):
        url = req.full_url
        self.calls.append((req.get_method(), url))
        if url.startswith("https://files.example/"):
            return _Resp(self.pdf)
        self._check_auth(req)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path.replace("/services/v2", "")
        doc = self.route(req.get_method(), path, q)
        if doc is None:
            raise urllib.error.HTTPError(url, 404, "Not found", {}, None)
        return _Resp(json.dumps(doc).encode())

    def route(self, method, path, q):
        if path in ("", "/"):
            return {"data": {"id": "1", "attributes": {"name": "Test Church"}}}
        if path == "/service_types":
            return {"data": self.types}
        m = re.fullmatch(r"/service_types/(\d+)/plans", path)
        if m:
            plans = sorted(self.plans.get(m.group(1), []), key=lambda p: p["attributes"]["sort_date"])
            if q.get("filter") == "future":
                plans = [p for p in plans if p["attributes"]["sort_date"][:10] >= date.today().isoformat()]
            elif q.get("filter") == "after":
                plans = [p for p in plans if p["attributes"]["sort_date"][:10] > q["after"]]
            return {"data": plans}
        m = re.fullmatch(r"/service_types/\d+/plans/\d+/items", path)
        if m:
            return {"data": self.items}
        m = re.fullmatch(r"/songs/5(\d)/arrangements/6\d/keys/7\d", path)
        if m:
            key = next(i["attributes"]["key_name"] for i in self.items if i["id"] == f"9{m.group(1)}")
            return {"data": {"id": "7" + m.group(1), "attributes": {"name": key, "starting_key": key}}}
        m = re.fullmatch(r"/songs/5(\d)/arrangements/6\d/keys/7\d/attachments", path)
        if m:
            i = m.group(1)
            key = next(x["attributes"]["key_name"] for x in self.items if x["id"] == f"9{i}")
            return {"data": [self._att(f"k{i}", f"Chord Chart - {key}.pdf", path)]}
        m = re.fullmatch(r"/songs/5(\d)/arrangements/6\d/attachments", path)
        if m:
            i = m.group(1)
            if i == "3":                  # Be Thou My Vision: only a lead sheet and an mp3, plus a chart in C
                return {"data": [self._att("a3a", "Lead Sheet.pdf", path), self._att("a3b", "Chord Chart - C.pdf", path),
                                 self._att("a3c", "Rehearsal.mp3", path, "audio/mpeg")]}
            return {"data": [self._att(f"a{i}", "Lyrics.pdf", path)]}
        m = re.fullmatch(r"(/songs/.*/attachments/\w+)/open", path)
        if m and method == "POST":
            return {"data": {"attributes": {"attachment_url": "https://files.example/" + m.group(1)}}}
        return None

    def _att(self, id_, filename, path, ctype="application/pdf"):
        return {"id": id_, "attributes": {"filename": filename, "content_type": ctype},
                "links": {"self": API + path + "/" + id_}}
