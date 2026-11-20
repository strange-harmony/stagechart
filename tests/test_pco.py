"""Planning Center client tests, against tests/fake_pco.py (no network).

    python -m unittest tests/test_pco.py -v      (needs tests/make_samples.py's sample, made on the fly)
"""
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "app"), os.path.join(ROOT, "tests")]

import pco  # noqa: E402
from fake_pco import FakePCO  # noqa: E402

SAMPLES = tempfile.mkdtemp()
subprocess.check_call([sys.executable, os.path.join(ROOT, "tests", "make_samples.py"), SAMPLES],
                      stdout=subprocess.DEVNULL)
SAMPLE = next(os.path.join(SAMPLES, f) for f in os.listdir(SAMPLES) if f.startswith("God"))


def client(fake=None):
    fake = fake or FakePCO(SAMPLE)
    return pco.Client("id", "secret", opener=fake.open, sleep=lambda s: None), fake


class Keys(unittest.TestCase):
    def test_same_key_ignores_spelling(self):
        self.assertTrue(pco.same_key("C#", "Db"))
        self.assertTrue(pco.same_key("Ebm", "D#m"))
        self.assertTrue(pco.same_key("F♯", "Gb"))
        self.assertFalse(pco.same_key("D", "Dm"))
        self.assertFalse(pco.same_key("D", "E"))
        self.assertFalse(pco.same_key("", "D"))

    def test_key_in_filename(self):
        self.assertTrue(pco._key_in_filename("God of the Promise - D.pdf", "D"))
        self.assertTrue(pco._key_in_filename("Song (Eb).pdf", "D#"))
        self.assertTrue(pco._key_in_filename("Song_Chord_Chart_key_F#.pdf", "Gb"))
        self.assertFalse(pco._key_in_filename("Song - E.pdf", "D"))
        self.assertFalse(pco._key_in_filename("A Mighty Fortress Is Our God - Chords.pdf", "A"))

    def test_pick_prefers_plan_key_then_chord_chart(self):
        A = pco.Attachment
        atts = [A("1", "Lead Sheet - D.pdf", "application/pdf", "u", "arrangement"),
                A("2", "Chord Chart - C.pdf", "application/pdf", "u", "arrangement"),
                A("3", "Chord Chart - D.pdf", "application/pdf", "u", "arrangement"),
                A("4", "Demo.mp3", "audio/mpeg", "u", "arrangement")]
        self.assertEqual(pco.pick_chart(atts, "D").id, "3")
        self.assertEqual(pco.pick_chart(atts, "C").id, "2")
        key_level = A("5", "Chart.pdf", "application/pdf", "u", "key", key_name="D")
        self.assertEqual(pco.pick_chart(atts[:2] + [key_level], "D").id, "5")
        self.assertIsNone(pco.pick_chart([atts[3]], "D"))


class ClientTests(unittest.TestCase):
    def test_bad_token(self):
        c = pco.Client("id", "wrong", opener=FakePCO(SAMPLE).open, sleep=lambda s: None)
        with self.assertRaises(pco.AuthError):
            c.check()

    def test_org_types_and_plans(self):
        c, fake = client()
        self.assertEqual(c.check(), "Test Church")
        types = c.service_types()
        self.assertEqual([t.name for t in types], ["Sunday Morning", "Youth"])
        nxt = c.next_plan(types)
        self.assertIsNotNone(nxt)
        self.assertGreaterEqual(nxt.day, date.today())
        start = nxt.day.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
        plans = c.plans_between(types, start, end)
        self.assertTrue(plans)
        self.assertTrue(all(start <= p.day < end for p in plans))
        self.assertEqual([p.day for p in plans], sorted(p.day for p in plans))
        self.assertIn("Youth Night", [p.title for p in plans] + ([] if any(
            p.service_type.name == "Youth" for p in plans) else ["Youth Night"]))

    def test_songs_keys_and_download(self):
        c, fake = client()
        plan = c.next_plan(c.service_types())
        songs = c.songs(plan)
        self.assertEqual([s.title for s in songs], ["God of the Test", "Come Thou Fount", "Be Thou My Vision",
                                                    "Amazing Grace"])                 # "Welcome" isn't a song
        self.assertEqual([s.key_name for s in songs], ["D", "E", "D", "G"])
        first = c.best_chart(songs[0])
        self.assertEqual((first.level, first.filename), ("key", "Chord Chart - D.pdf"))
        # no key on the plan item: picks the arrangement's chord chart, never the lead sheet or mp3
        btmv = c.best_chart(songs[2])
        self.assertEqual(btmv.filename, "Chord Chart - C.pdf")
        dest = os.path.join(tempfile.mkdtemp(), "x", "chart.pdf")
        c.download(first, dest)
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(4), b"%PDF")
        self.assertIn(("POST", first.url + "/open"), fake.calls)

    def test_rate_limit_is_retried(self):
        fake = FakePCO(SAMPLE)
        real = fake.open
        hits = {"n": 0}

        def flaky(req, timeout=30):
            hits["n"] += 1
            if hits["n"] == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "1"}, None)
            return real(req, timeout)
        c = pco.Client("id", "secret", opener=flaky, sleep=lambda s: None)
        self.assertEqual(c.check(), "Test Church")
        self.assertEqual(hits["n"], 2)

    def test_folder_names(self):
        st = pco.ServiceType("1", "Sunday Morning")
        p = pco.Plan("9", st, date(2026, 11, 22), "November 22, 2026", series="Advent: Week 1")
        self.assertEqual(os.path.basename(pco.plan_folder("/x", p)), "2026-11-22 Sunday Morning - Advent- Week 1")


class SetPDF(unittest.TestCase):
    def test_combine(self):
        import setpdf
        from pypdf import PdfReader
        out = os.path.join(tempfile.mkdtemp(), "set.pdf")
        n = setpdf.combine([SAMPLE, SAMPLE], out, ["One", "Two"])
        self.assertEqual(n, 2 * len(PdfReader(SAMPLE).pages))
        self.assertEqual(len(PdfReader(out).pages), n)


if __name__ == "__main__":
    unittest.main()
