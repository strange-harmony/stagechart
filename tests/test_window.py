"""Runs tests/window_check.py (the real window, a dropped PDF and a whole fake Planning Center set).

Needs a display: CI runs it under xvfb-run. Skipped when there is none.
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform in ("win32", "darwin"), "no display")
class WindowTest(unittest.TestCase):
    def test_window(self):
        samples = tempfile.mkdtemp()
        subprocess.check_call([sys.executable, os.path.join(ROOT, "tests", "make_samples.py"), samples],
                              stdout=subprocess.DEVNULL)
        sample = next(os.path.join(samples, f) for f in os.listdir(samples) if f.startswith("God"))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "window_check.py"), sample],
                           capture_output=True, text=True, timeout=300)
        print(r.stdout, r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("window check: all good", r.stdout)


if __name__ == "__main__":
    unittest.main()
