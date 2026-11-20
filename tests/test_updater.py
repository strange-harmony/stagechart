"""Tests for app/updater.py that run anywhere (no GitHub, no real install).

    python3 -m unittest tests/test_updater.py
"""
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import updater  # noqa: E402


class Server:
    """A tiny stand-in for api.github.com and the download host."""

    def __init__(self):
        self.routes = {}
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                r = outer.routes.get(self.path)
                if r is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                code, headers, body = r
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse_version("v1.2"), (1, 2, 0))
        self.assertEqual(updater.parse_version("1.2.3-beta"), (1, 2, 3))
        self.assertEqual(updater.parse_version(""), (0, 0, 0))

    def test_newer(self):
        self.assertTrue(updater.is_newer("1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer("v1.0", "1.0.0"))
        self.assertFalse(updater.is_newer("0.9", "1.0.0"))

    def test_due(self):
        self.assertTrue(updater.due_for_check({"auto_check": True, "last_check": 0}))
        self.assertFalse(updater.due_for_check({"auto_check": False, "last_check": 0}))
        self.assertFalse(updater.due_for_check({"auto_check": True, "last_check": time.time()}))


class CheckAndDownloadTests(unittest.TestCase):
    def setUp(self):
        self.srv = Server()
        self.old_api = updater.API
        updater.API = self.srv.url + "/repos/x/y"
        self.tmp = tempfile.mkdtemp()
        self.payload = zip_bytes({"Stage Chart/Stage Chart.exe": b"MZ", "Stage Chart/app/version.py":
                                  b'VERSION = "9.1.0"\n', "Stage Chart/runtime/python.exe": b"MZ"})
        # the asset URL redirects once, like GitHub's does
        self.srv.routes["/dl/StageChart-windows.zip"] = (302, {"Location": "/blob/abc"}, b"")
        self.srv.routes["/blob/abc"] = (200, {}, self.payload)

    def tearDown(self):
        updater.API = self.old_api
        self.srv.stop()
        shutil.rmtree(self.tmp)

    def release(self, tag="v9.1.0", digest=None, name="StageChart-windows.zip"):
        digest = digest or "sha256:" + hashlib.sha256(self.payload).hexdigest()
        body = {"tag_name": tag, "body": "Fixes things.", "html_url": "https://example/rel",
                "assets": [{"name": name, "size": len(self.payload), "digest": digest,
                            "browser_download_url": self.srv.url + "/dl/StageChart-windows.zip"}]}
        self.srv.routes["/repos/x/y/releases/latest"] = (200, {}, json.dumps(body).encode())

    def test_up_to_date(self):
        self.release(tag="v" + updater.VERSION)
        self.assertIsNone(updater.check("windows"))

    def test_no_releases(self):
        with self.assertRaises(updater.UpdateError) as cm:
            updater.check("windows")
        self.assertIn("No Stage Chart releases", str(cm.exception))

    def test_missing_asset(self):
        self.release(name="something-else.zip")
        with self.assertRaises(updater.UpdateError):
            updater.check("windows")

    def test_download_and_verify(self):
        self.release()
        rel = updater.check("windows")
        self.assertEqual(rel["version"], "9.1.0")
        self.assertEqual(rel["notes"], "Fixes things.")
        seen = []
        path = updater.download(rel, self.tmp, lambda d, t: seen.append((d, t)))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), self.payload)
        self.assertEqual(seen[-1], (len(self.payload), len(self.payload)))

    def test_bad_checksum(self):
        self.release(digest="sha256:" + "0" * 64)
        rel = updater.check("windows")
        with self.assertRaises(updater.UpdateError):
            updater.download(rel, self.tmp)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_prepare_windows_layout(self):
        self.release()
        rel = updater.check("windows")
        path = updater.download(rel, self.tmp)
        old = updater.IS_MAC, updater.IS_WIN
        updater.IS_MAC, updater.IS_WIN = False, True
        try:
            new = updater.prepare(path, "9.1.0")
            self.assertTrue(os.path.isfile(os.path.join(new, "Stage Chart.exe")))
            with self.assertRaises(updater.UpdateError):
                updater.prepare(path, "9.2.0")
        finally:
            updater.IS_MAC, updater.IS_WIN = old


@unittest.skipIf(sys.platform == "win32", "needs /bin/sh")
class MacSwapScriptTests(unittest.TestCase):
    """Runs the Mac helper script with stand-ins for macOS's open/xattr/defaults."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for tool in ("open", "xattr", "defaults"):
            p = os.path.join(self.bin, tool)
            with open(p, "w") as fh:
                fh.write(f'#!/bin/sh\necho "{tool} $*" >> "{self.tmp}/calls"\n')
            os.chmod(p, 0o755)
        self.app = os.path.join(self.tmp, "Applications", "Stage Chart.app")
        os.makedirs(os.path.join(self.app, "Contents"))
        with open(os.path.join(self.app, "Contents", "v"), "w") as fh:
            fh.write("old")
        self.work = os.path.join(self.tmp, "work")
        self.new = os.path.join(self.work, "new", "Stage Chart", "Stage Chart.app")
        os.makedirs(os.path.join(self.new, "Contents"))
        with open(os.path.join(self.new, "Contents", "v"), "w") as fh:
            fh.write("new")
        self.script = os.path.join(self.work, "swap.sh")
        with open(self.script, "w") as fh:
            fh.write(updater.MAC_SWAP)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_swap(self, pid):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"])
        return subprocess.run(["/bin/sh", self.script, str(pid), self.app, self.new, self.work,
                               os.path.join(self.tmp, "log")], env=env, timeout=30)

    def test_waits_then_swaps(self):
        sleeper = subprocess.Popen(["sleep", "1"])
        threading.Thread(target=sleeper.wait, daemon=True).start()     # reap it, or it lingers as a zombie
        t0 = time.time()
        r = self.run_swap(sleeper.pid)
        self.assertGreater(time.time() - t0, 0.8)
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.app, "Contents", "v")) as fh:
            self.assertEqual(fh.read(), "new")
        self.assertFalse(os.path.exists(self.work))
        with open(os.path.join(self.tmp, "calls")) as fh:
            self.assertIn(f"open {self.app}", fh.read())

    def test_rolls_back(self):
        shutil.rmtree(self.new)                     # nothing to move in: must restore the old app
        r = self.run_swap(999999)
        self.assertEqual(r.returncode, 1)
        with open(os.path.join(self.app, "Contents", "v")) as fh:
            self.assertEqual(fh.read(), "old")


if __name__ == "__main__":
    unittest.main()
