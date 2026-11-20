"""Download what the Windows build needs, on any OS with Python 3.10+ and pip.

  python3 windows/fetch_windows_deps.py WORK_DIR

Makes WORK_DIR/runtime (conda-forge Python 3.12 + Tk 8.6 for win-64, unpacked) and WORK_DIR/wheels
(win_amd64 wheels for pdfminer.six, reportlab, tkinterdnd2, pypdf and their dependencies).
Needs the 'zstandard' module (pip install zstandard) to unpack .conda packages.
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

CHANNEL = "https://conda.anaconda.org/conda-forge/win-64/"
PYTHON = "3.12"
# name -> version prefix to accept (None: newest)
RUNTIME = {"python": PYTHON + ".", "libpython": PYTHON + ".", "tk": "8.6.", "bzip2": None, "libexpat": None,
           "libffi": "3.", "liblzma": None, "libsqlite": None, "libzlib": None, "openssl": "3.",
           "vc14_runtime": None}
WHEELS = ["pdfminer.six", "reportlab", "tkinterdnd2", "pypdf"]   # pypdf: one PDF per set


def fetch(url):
    with urllib.request.urlopen(url, timeout=600) as r:
        return r.read()


def pick(repodata):
    pk = {**repodata.get("packages", {}), **repodata.get("packages.conda", {})}
    chosen = {}
    py = max(((p.get("timestamp", 0), fn, p) for fn, p in pk.items() if p["name"] == "python"
              and p["version"].startswith(RUNTIME["python"]) and "cpython" in p["build"]))
    chosen["python"] = py[1]
    # libpython must match python's exact build; it isn't always in current_repodata
    lp = [d for d in py[2]["depends"] if d.startswith("libpython ")]
    if lp:
        _, ver, build = lp[0].split()
        chosen["libpython"] = f"libpython-{ver}-{build}.conda"
    for name, prefix in RUNTIME.items():
        if name in chosen or name == "libpython":
            continue
        c = [(p.get("timestamp", 0), fn) for fn, p in pk.items()
             if p["name"] == name and (prefix is None or p["version"].startswith(prefix))]
        chosen[name] = max(c)[1]
    return chosen


def unpack_conda(data, dest):
    import zstandard
    outer = zipfile.ZipFile(io.BytesIO(data))
    for n in outer.namelist():
        if n.startswith("pkg-") and n.endswith(".tar.zst"):
            raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(outer.read(n)))
            with tarfile.open(fileobj=raw, mode="r|") as tf:
                tf.extractall(dest, filter="data") if sys.version_info >= (3, 12) else tf.extractall(dest)


def main(work):
    rt = os.path.join(work, "runtime")
    wh = os.path.join(work, "wheels")
    os.makedirs(rt, exist_ok=True)
    os.makedirs(wh, exist_ok=True)
    repo = json.loads(fetch(CHANNEL + "current_repodata.json"))
    chosen = pick(repo)
    with open(os.path.join(work, "runtime-packages.txt"), "w") as fh:
        fh.write("\n".join(chosen.values()) + "\n")
    for name, fn in chosen.items():
        print("runtime:", fn)
        unpack_conda(fetch(CHANNEL + fn), rt)
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--only-binary=:all:",
                           "--platform", "win_amd64", "--python-version", PYTHON, "--implementation", "cp",
                           "--abi", "cp" + PYTHON.replace(".", ""), "-d", wh] + WHEELS)
    print("wheels:", ", ".join(sorted(os.listdir(wh))))


if __name__ == "__main__":
    main(sys.argv[1])
