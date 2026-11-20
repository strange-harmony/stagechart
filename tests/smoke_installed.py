"""Smoke test for a built Stage Chart on a real Mac or Windows PC (used by .github/workflows/release.yml).

    python tests/smoke_installed.py INSTALL SAMPLES_DIR

INSTALL is the installed app: ".../Stage Chart.app" on a Mac, or the "Stage Chart" folder (the one with
"Stage Chart.exe") on Windows. Uses only the app's own bundled Python, and checks that:
  1. it converts the sample PDFs (tests/make_samples.py) into stage charts,
  2. Tk starts (the window toolkit),
  3. it can reach GitHub over HTTPS (needed for update checks),
  4. the window opens and works: a dropped PDF and a whole (fake) Planning Center set are converted, the
     set is put together in one PDF, and the Planning Center token store (keychain / Credential Manager)
     keeps and forgets a token (tests/window_check.py),
  5. an update really installs: a copy of the app marked 99.0.0 is zipped like a release, the installed
     app's own updater unpacks it and starts the swap helper, and the test waits until the installed copy
     says 99.0.0 and the helper has started it again.
The installed copy is changed by step 4, so run this on a throwaway copy.
"""
import glob
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

IS_MAC = sys.platform == "darwin"
NEW_VERSION = "99.0.0"


def paths(install):
    if IS_MAC:
        return (os.path.join(install, "Contents", "MacOS", "python3.12"),
                os.path.join(install, "Contents", "Resources", "app"))
    return os.path.join(install, "runtime", "python.exe"), os.path.join(install, "app")


def run_py(install, code, *args, timeout=300):
    py, app = paths(install)
    env = dict(os.environ)
    if IS_MAC:
        env["TCL_LIBRARY"] = os.path.join(install, "Contents", "lib", "tcl8.6")
        env["TK_LIBRARY"] = os.path.join(install, "Contents", "lib", "tk8.6")
    else:
        env["TCL_LIBRARY"] = os.path.join(install, "runtime", "tcl", "tcl8.6")
        env["TK_LIBRARY"] = os.path.join(install, "runtime", "tcl", "tk8.6")
    prelude = (f"import sys; sys.path[:0] = [{app!r}, {os.path.join(app, 'vendor')!r}]; "
               "sys.argv[1:] = " + repr(list(args)) + "\n")
    # -X utf8: the engine prints ×, → and ♯, which a Windows console code page can't encode
    r = subprocess.run([py, "-B", "-E", "-s", "-X", "utf8", "-c", prelude + code], capture_output=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env)
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr)
        raise SystemExit(f"FAILED: bundled Python exited with {r.returncode}")
    return r.stdout


def step(n, text):
    print(f"\n=== {n}. {text}", flush=True)


def convert(install, samples):
    pdfs = sorted(glob.glob(os.path.join(samples, "*.pdf")))
    if not pdfs:
        raise SystemExit("FAILED: no sample PDFs")
    out = tempfile.mkdtemp()
    run_py(install, "import stagechart; sys.exit(stagechart.main(sys.argv[1:]))", *pdfs, "--out", out)
    made = glob.glob(os.path.join(out, "*Stage Chart*.pdf"))
    if len(made) != len(pdfs):
        raise SystemExit(f"FAILED: expected {len(pdfs)} stage charts, got {made}")


def tk_starts(install):
    run_py(install, "import tkinter; r = tkinter.Tk(); r.update(); print('Tk', r.tk.call('info', 'patchlevel')); "
                    "r.destroy()")


def https_works(install):
    run_py(install, "import updater; r = updater._open('https://api.github.com/rate_limit'); "
                    "print('GitHub HTTPS', r.status)")


def window_works(install, samples):
    tests = os.path.dirname(os.path.abspath(__file__))
    sample = sorted(glob.glob(os.path.join(samples, "God*.pdf")) or glob.glob(os.path.join(samples, "*.pdf")))[0]
    out = run_py(install, f"sys.path.insert(0, {tests!r}); import window_check; window_check.check(sys.argv[1])",
                 sample)
    if "window check: all good" not in out:
        raise SystemExit("FAILED: window check")
    if not IS_MAC and "drag and drop: on" not in out:
        raise SystemExit("FAILED: drag and drop didn't load in the Windows app")


def make_release_zip(install, dest_zip):
    """Copy the install, mark it NEW_VERSION, and zip it the way the release workflow does."""
    stage = tempfile.mkdtemp()
    top = os.path.join(stage, "Stage Chart")
    if IS_MAC:
        os.makedirs(top)
        app = os.path.join(top, "Stage Chart.app")
        subprocess.check_call(["ditto", install, app])
        plist = os.path.join(app, "Contents", "Info.plist")
        with open(plist, "rb") as fh:
            info = plistlib.load(fh)
        info["CFBundleShortVersionString"] = info["CFBundleVersion"] = NEW_VERSION
        with open(plist, "wb") as fh:
            plistlib.dump(info, fh)
        set_version(os.path.join(app, "Contents", "Resources", "app", "version.py"))
        subprocess.check_call(["ditto", "-c", "-k", "--keepParent", top, dest_zip])
    else:
        shutil.copytree(install, top, ignore=shutil.ignore_patterns("_update"))
        set_version(os.path.join(top, "app", "version.py"))
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _, files in os.walk(top):
                for f in files:
                    p = os.path.join(dirpath, f)
                    zf.write(p, os.path.relpath(p, stage))
    shutil.rmtree(stage)


def set_version(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(re.sub(r'VERSION = "[^"]*"', f'VERSION = "{NEW_VERSION}"', text))


def installed_version(install):
    p = os.path.join(paths(install)[1], "version.py")
    try:
        with open(p, encoding="utf-8") as fh:
            m = re.search(r'VERSION = "([^"]*)"', fh.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def update_installs(install):
    before = installed_version(install)
    zsrc = os.path.join(tempfile.mkdtemp(), "StageChart-update.zip")
    make_release_zip(install, zsrc)
    log = os.path.join(tempfile.mkdtemp(), "update.log")
    # Inside the installed app: check it may update, unpack the zip with its own updater, start the swap
    # helper, then exit (like the window does after "Install and Restart").
    run_py(install, """
import os, shutil, updater
ok, why = updater.can_install()
print('can_install', ok, why)
assert ok, why
work = updater.work_dir()
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
z = os.path.join(work, updater.ASSETS[updater.platform_key()])
shutil.copy(sys.argv[1], z)
new = updater.prepare(z, sys.argv[2])
print('prepared', new)
updater.launch_swap(new, sys.argv[3])
""", zsrc, NEW_VERSION, log)
    deadline = time.time() + 120
    while time.time() < deadline:
        if installed_version(install) == NEW_VERSION and os.path.exists(log) and "installed" in open(log).read():
            break
        time.sleep(1)
    print("log:", open(log).read() if os.path.exists(log) else "(none)")
    got = installed_version(install)
    if got != NEW_VERSION:
        raise SystemExit(f"FAILED: still version {got} (was {before}) after the update")
    time.sleep(5)                                  # the helper starts Stage Chart again; let it come up
    relaunched = stop_app(install)
    print("relaunched after update:", relaunched)
    if not relaunched:
        raise SystemExit("FAILED: Stage Chart wasn't started again after the update")


def stop_app(install):
    """Stop the Stage Chart that the helper started. Returns True if one was running."""
    if IS_MAC:
        r = subprocess.run(["pkill", "-f", os.path.join(install, "Contents")])
        return r.returncode == 0
    ps = ("$p = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like ($env:SC_DIR + '*') }; "
          "if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; exit 0 } else { exit 1 }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       env=dict(os.environ, SC_DIR=os.path.join(install, "runtime")))
    return r.returncode == 0


def main(install, samples):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # the CI console may not be UTF-8
    install = os.path.abspath(install)
    step(1, "convert sample charts")
    convert(install, samples)
    step(2, "start Tk")
    tk_starts(install)
    step(3, "reach GitHub over HTTPS")
    https_works(install)
    step(4, "open the window, convert a dropped PDF and a whole Planning Center set")
    window_works(install, samples)
    step(5, "install an update and restart")
    update_installs(install)
    print("\nALL OK")


if __name__ == "__main__":
    main(*sys.argv[1:3])
