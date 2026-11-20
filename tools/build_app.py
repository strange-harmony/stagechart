"""Assemble "Stage Chart.app" (universal: Apple silicon + Intel) from conda-forge Python builds.

Run on Linux or macOS:
  python3 tools/build_app.py RUNTIME_ARM64 RUNTIME_X86_64 WHEELS_DIR OUT_DIR

RUNTIME_*  : extracted conda-forge python 3.12 + tk prefixes for osx-arm64 and osx-64
WHEELS_DIR : pdfminer.six, reportlab, charset-normalizer (universal2), cryptography (universal2),
             pycparser, and cffi wheels in subfolders cffi_arm64/ and cffi_x86_64/
Needs llvm-lipo (or lipo) on PATH to merge Mach-O files.
"""
import filecmp
import glob
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIPO = shutil.which("lipo") or shutil.which("llvm-lipo") or shutil.which("llvm-lipo-18")
sys.path.insert(0, os.path.join(ROOT, "app"))
from version import VERSION  # noqa: E402  (the release workflow sets it)

DROP_DYLIBS = ("libpython", "libncurses", "libtinfo", "libform", "libmenu", "libpanel", "libreadline",
               "libhistory", "libsqlite")
DROP_MODULES = ("_curses", "_curses_panel", "readline", "_sqlite3", "_dbm", "_gdbm", "_test", "xxlimited",
                "_xxtestfuzz", "_ctypes_test")
KEEP_LIB_DIRS = {"python3.12", "tcl8.6", "tk8.6", "tcl8"}
DROP_STDLIB = {"test", "idlelib", "ensurepip", "lib2to3", "turtledemo", "pydoc_data", "config-3.12-darwin",
               "venv", "unittest", "tkinter/test", "sqlite3/test", "ctypes/test", "distutils/tests",
               "site-packages"}


def is_macho(path):
    try:
        with open(path, "rb") as fh:
            m = fh.read(4)
    except OSError:
        return False
    return m in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe")


def copy_lib(src_prefix, dst_lib):
    src_lib = os.path.join(src_prefix, "lib")
    for name in os.listdir(src_lib):
        sp = os.path.join(src_lib, name)
        dp = os.path.join(dst_lib, name)
        if os.path.isdir(sp) and not os.path.islink(sp):
            if name in KEEP_LIB_DIRS:
                shutil.copytree(sp, dp, symlinks=True, dirs_exist_ok=True)
        elif name.endswith(".dylib") and not name.startswith(DROP_DYLIBS):
            if os.path.islink(sp):
                if not os.path.lexists(dp):
                    os.symlink(os.readlink(sp), dp)
            else:
                shutil.copy2(sp, dp)
    dyn = os.path.join(dst_lib, "python3.12", "lib-dynload")
    for f in os.listdir(dyn):
        if f.split(".")[0] in DROP_MODULES or f.startswith(("_test", "xx")):
            os.remove(os.path.join(dyn, f))
    for d in DROP_STDLIB:
        shutil.rmtree(os.path.join(dst_lib, "python3.12", d), ignore_errors=True)


def merge_universal(arm, x86, out):
    """Copy the arm64 tree to out, then fold in x86_64 slices of every Mach-O file."""
    for dirpath, dirs, files in os.walk(x86):
        rel = os.path.relpath(dirpath, x86)
        for f in files:
            xp = os.path.join(dirpath, f)
            op = os.path.join(out, rel, f)
            if os.path.islink(xp):
                if not os.path.lexists(op):
                    os.makedirs(os.path.dirname(op), exist_ok=True)
                    os.symlink(os.readlink(xp), op)
                continue
            if not os.path.exists(op):
                os.makedirs(os.path.dirname(op), exist_ok=True)
                shutil.copy2(xp, op)
                continue
            if filecmp.cmp(op, xp, shallow=False):
                continue
            if is_macho(op) and is_macho(xp):
                tmp = op + ".fat"
                subprocess.run([LIPO, "-create", op, xp, "-output", tmp], check=True)
                os.replace(tmp, op)
                os.chmod(op, 0o755)


def build(rt_arm, rt_x86, wheels, out_dir):
    app = os.path.join(out_dir, "Stage Chart.app")
    shutil.rmtree(app, ignore_errors=True)
    C = os.path.join(app, "Contents")
    for d in ("MacOS", "lib", "Resources"):
        os.makedirs(os.path.join(C, d), exist_ok=True)

    # ---- universal runtime
    stage = os.path.join(out_dir, "_stage")
    shutil.rmtree(stage, ignore_errors=True)
    for arch, rt in (("arm64", rt_arm), ("x86_64", rt_x86)):
        lib = os.path.join(stage, arch, "lib")
        os.makedirs(lib)
        copy_lib(rt, lib)
        os.makedirs(os.path.join(stage, arch, "MacOS"))
        shutil.copy2(os.path.join(rt, "bin", "python3.12"), os.path.join(stage, arch, "MacOS", "python3.12"))
    # vendored packages: pure Python plus universal2 wheels; cffi needs its two slices merged
    vend_arm = os.path.join(stage, "arm64", "vendor")
    vend_x86 = os.path.join(stage, "x86_64", "vendor")
    for v in (vend_arm, vend_x86):
        os.makedirs(v)
        for w in glob.glob(os.path.join(wheels, "*.whl")):
            zipfile.ZipFile(w).extractall(v)
    for w in glob.glob(os.path.join(wheels, "cffi_arm64", "*.whl")):
        zipfile.ZipFile(w).extractall(vend_arm)
    for w in glob.glob(os.path.join(wheels, "cffi_x86_64", "*.whl")):
        zipfile.ZipFile(w).extractall(vend_x86)
    merged = os.path.join(stage, "universal")
    shutil.copytree(os.path.join(stage, "arm64"), merged, symlinks=True)
    merge_universal(os.path.join(stage, "arm64"), os.path.join(stage, "x86_64"), merged)

    shutil.copytree(os.path.join(merged, "lib"), os.path.join(C, "lib"), symlinks=True, dirs_exist_ok=True)
    shutil.copy2(os.path.join(merged, "MacOS", "python3.12"), os.path.join(C, "MacOS", "python3.12"))

    # ---- app code
    res_app = os.path.join(C, "Resources", "app")
    shutil.copytree(os.path.join(ROOT, "app"), res_app,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "vendor"))
    shutil.copytree(os.path.join(merged, "vendor"), os.path.join(res_app, "vendor"),
                    ignore=shutil.ignore_patterns("*.dist-info", "*.data", "__pycache__"))
    stub = os.path.join(ROOT, "tools", "pil_stub")
    shutil.copytree(stub, os.path.join(res_app, "vendor", "PIL"))
    shutil.rmtree(os.path.join(res_app, "vendor", "reportlab", "fonts"), ignore_errors=True)
    os.makedirs(os.path.join(res_app, "vendor", "reportlab", "fonts"))
    dnd = os.path.join(res_app, "vendor", "tkinterdnd2", "tkdnd")
    if os.path.isdir(dnd):                    # keep only the Mac builds of tkdnd (Tk 8.6, both chips)
        for d in os.listdir(dnd):
            if os.path.isdir(os.path.join(dnd, d)) and d not in ("osx-arm64", "osx-x64"):
                shutil.rmtree(os.path.join(dnd, d))
    shutil.rmtree(os.path.join(res_app, "vendor", "tkinterdnd2", "__pyinstaller"), ignore_errors=True)

    # ---- launcher
    launcher = os.path.join(C, "MacOS", "StageChart")
    with open(launcher, "w", newline="\n") as fh:
        fh.write("""#!/bin/bash
# Stage Chart launcher: runs the bundled Python with the app's window.
C="$(cd "$(dirname "$0")/.." && pwd -P)"
export TCL_LIBRARY="$C/lib/tcl8.6"
export TK_LIBRARY="$C/lib/tk8.6"
export LANG="${LANG:-en_US.UTF-8}"
exec "$C/MacOS/python3.12" -B -E -s "$C/Resources/app/gui.py" "$@"
""")
    os.chmod(launcher, 0o755)
    os.chmod(os.path.join(C, "MacOS", "python3.12"), 0o755)

    shutil.copy2(os.path.join(ROOT, "tools", "AppIcon.icns"), os.path.join(C, "Resources", "AppIcon.icns"))
    info = {
        "CFBundleName": "Stage Chart",
        "CFBundleDisplayName": "Stage Chart",
        "CFBundleIdentifier": "app.stagechart.converter",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "StageChart",
        "CFBundleIconFile": "AppIcon",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.music",
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "PDF chord chart",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["com.adobe.pdf"],
        }],
    }
    with open(os.path.join(C, "Info.plist"), "wb") as fh:
        plistlib.dump(info, fh)
    with open(os.path.join(C, "PkgInfo"), "w") as fh:
        fh.write("APPL????")
    shutil.rmtree(stage)
    return app


def zip_app(app, zpath):
    """Zip with symlinks and Unix permissions kept, so Finder unzips a working app."""
    if os.path.exists(zpath):
        os.remove(zpath)
    base = os.path.dirname(app)
    zf = zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9)
    for dirpath, dirs, files in os.walk(app):
        dirs.sort()
        for name in sorted(dirs + files):
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, base)
            st = os.lstat(p)
            if os.path.islink(p):
                zi = zipfile.ZipInfo(rel)
                zi.create_system = 3
                zi.external_attr = (stat.S_IFLNK | 0o755) << 16
                zf.writestr(zi, os.readlink(p))
            elif os.path.isdir(p):
                zi = zipfile.ZipInfo(rel + "/")
                zi.create_system = 3
                zi.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                zf.writestr(zi, b"")
            else:
                zi = zipfile.ZipInfo.from_file(p, rel)
                zi.create_system = 3
                mode = 0o755 if st.st_mode & 0o111 else 0o644
                zi.external_attr = (stat.S_IFREG | mode) << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(p, "rb") as fh:
                    zf.writestr(zi, fh.read())
    zf.close()


def package(app, readme, zpath):
    """Stage Chart.zip: a "Stage Chart" folder with the app and the install notes."""
    staging = os.path.join(os.path.dirname(app), "Stage Chart")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    shutil.move(app, os.path.join(staging, "Stage Chart.app"))
    shutil.copy2(readme, os.path.join(staging, "How to install.txt"))
    zip_app(staging, zpath)
    return staging


if __name__ == "__main__":
    a, x, w, o = sys.argv[1:5]
    os.makedirs(o, exist_ok=True)
    app = build(a, x, w, o)
    if len(sys.argv) > 5:
        package(app, os.path.join(ROOT, "How to install.txt"), sys.argv[5])
        print(sys.argv[5])
    else:
        print(app)
