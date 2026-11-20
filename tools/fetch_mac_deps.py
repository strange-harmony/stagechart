"""Download what the Mac build needs, on any OS with Python 3.10+ and pip.

  python3 tools/fetch_mac_deps.py WORK_DIR

Makes, for tools/build_app.py:
  WORK_DIR/runtime-arm64    conda-forge Python 3.12 + Tk 8.6 for osx-arm64, unpacked
  WORK_DIR/runtime-x86_64   the same for osx-64
  WORK_DIR/wheels           pure Python and universal2 wheels, plus cffi_arm64/ and cffi_x86_64/

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

CHANNEL = "https://conda.anaconda.org/conda-forge/"
ARCHES = {"arm64": "osx-arm64", "x86_64": "osx-64"}
PYTHON = "3.12"
# name -> version prefix to accept (None: newest). Only what Contents/lib keeps; see build_app.copy_lib.
RUNTIME = {"python": PYTHON + ".", "tk": "8.6.", "bzip2": None, "libexpat": None, "libffi": "3.",
           "liblzma": None, "libzlib": None, "openssl": "3."}
# --no-deps: Pillow must stay out (tools/pil_stub stands in for it). certifi gives the bundled
# Python the root certificates it needs to reach GitHub for updates.
WHEELS = ["pdfminer.six", "reportlab", "charset-normalizer", "cryptography", "pycparser", "certifi"]
CFFI = {"arm64": "macosx_11_0_arm64", "x86_64": "macosx_10_9_x86_64"}


def fetch(url):
    with urllib.request.urlopen(url, timeout=600) as r:
        return r.read()


def pick(repodata):
    pk = {**repodata.get("packages", {}), **repodata.get("packages.conda", {})}
    chosen = {}
    for name, prefix in RUNTIME.items():
        c = [(p.get("timestamp", 0), fn) for fn, p in pk.items()
             if p["name"] == name and (prefix is None or p["version"].startswith(prefix))
             and (name != "python" or "cpython" in p["build"])]
        chosen[name] = max(c)[1]
    return chosen


def unpack(fn, data, dest):
    if fn.endswith(".tar.bz2"):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as tf:
            _extract(tf, dest)
        return
    import zstandard
    outer = zipfile.ZipFile(io.BytesIO(data))
    for n in outer.namelist():
        if n.startswith("pkg-") and n.endswith(".tar.zst"):
            raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(outer.read(n)))
            with tarfile.open(fileobj=raw, mode="r|") as tf:
                _extract(tf, dest)


def _extract(tf, dest):
    if sys.version_info >= (3, 12):
        tf.extractall(dest, filter="tar")     # keeps the dylib symlinks inside the prefix
    else:
        tf.extractall(dest)


def pip_download(dest, platform, pkgs):
    subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:",
                           "--platform", platform, "--python-version", PYTHON, "--implementation", "cp",
                           "--abi", "cp" + PYTHON.replace(".", ""), "--abi", "abi3", "--abi", "none",
                           "-d", dest] + pkgs)


def main(work):
    listing = []
    for arch, sub in ARCHES.items():
        rt = os.path.join(work, "runtime-" + arch)
        os.makedirs(rt, exist_ok=True)
        repo = json.loads(fetch(CHANNEL + sub + "/current_repodata.json"))
        for name, fn in pick(repo).items():
            print(f"runtime {arch}:", fn)
            listing.append(f"{sub}/{fn}")
            unpack(fn, fetch(CHANNEL + sub + "/" + fn), rt)
    with open(os.path.join(work, "runtime-packages.txt"), "w") as fh:
        fh.write("\n".join(listing) + "\n")

    wh = os.path.join(work, "wheels")
    os.makedirs(wh, exist_ok=True)
    pip_download(wh, "macosx_11_0_universal2", WHEELS)
    for arch, plat in CFFI.items():
        pip_download(os.path.join(wh, "cffi_" + arch), plat, ["cffi"])
    print("wheels:", ", ".join(sorted(os.listdir(wh))))


if __name__ == "__main__":
    main(sys.argv[1])
