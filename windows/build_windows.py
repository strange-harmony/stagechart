"""Assemble the Windows "Stage Chart" folder (and optionally "Stage Chart for Windows.zip").

Run on Linux (or Windows with MSYS2 mingw-w64):
  python3 windows/fetch_windows_deps.py WORK
  python3 windows/build_windows.py WORK/runtime WORK/wheels OUT_DIR [ZIP_PATH]

Needs x86_64-w64-mingw32-gcc and x86_64-w64-mingw32-windres (Ubuntu: apt install gcc-mingw-w64-x86-64),
and optionally python3.12 on PATH to precompile the Python files.

Result:
  Stage Chart/
    Stage Chart.exe        small launcher (starts runtime\\pythonw.exe with app\\gui_win.py)
    How to install.txt
    app/                   ../app/stagechart.py and fonts (shared with the Mac app), windows/app/*.py, packages
    runtime/               Python 3.12 + Tcl/Tk 8.6 (conda-forge build), nothing installed system-wide
"""
import glob
import os
import shutil
import subprocess
import sys
import zipfile

WIN = os.path.dirname(os.path.abspath(__file__))     # windows/
ROOT = os.path.dirname(WIN)                           # repository root: app/, tools/
CC = "x86_64-w64-mingw32-gcc"
WINDRES = "x86_64-w64-mingw32-windres"

ROOT_FILES = ("python.exe", "pythonw.exe", "python3.dll", "python312.dll", "vcruntime140.dll",
              "vcruntime140_1.dll", "LICENSE_PYTHON.txt")
LIB_BIN = ("ffi-8.dll", "libbz2.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll", "libexpat.dll", "liblzma.dll",
           "sqlite3.dll", "tcl86t.dll", "tk86t.dll", "zlib.dll", "zlib1.dll")   # tcl86t.dll needs zlib1.dll
DROP_PYD = ("_test", "xxlimited", "_ctypes_test", "_msi")
DROP_STDLIB = {"test", "idlelib", "ensurepip", "lib2to3", "turtledemo", "pydoc_data", "venv", "site-packages",
               "tkinter/test", "sqlite3/test", "ctypes/test", "unittest/test"}
TCL_DIRS = ("tcl8.6", "tk8.6", "tcl8")
DROP_TCL = ("tk8.6/demos", "tk8.6/images", "tcl8.6/tzdata")


def make_icon(dst):
    shutil.copy2(os.path.join(ROOT, "tools", "AppIcon.ico"), dst)       # drawn by tools/make_icon.py


def build_launcher(out_exe, ico):
    work = os.path.join(os.path.dirname(out_exe), "_launcher")
    os.makedirs(work, exist_ok=True)
    shutil.copy2(ico, os.path.join(work, "StageChart.ico"))
    shutil.copy2(os.path.join(WIN, "launcher", "launcher.rc"), os.path.join(work, "launcher.rc"))
    res = os.path.join(work, "launcher_res.o")
    subprocess.check_call([WINDRES, "launcher.rc", "-O", "coff", "-o", res], cwd=work)
    subprocess.check_call([CC, "-O2", "-s", "-municode", "-mwindows", "-static",
                           os.path.join(WIN, "launcher", "launcher.c"), res, "-o", out_exe])
    shutil.rmtree(work)


def copy_runtime(src, dst):
    os.makedirs(dst)
    for f in ROOT_FILES:
        shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    for f in LIB_BIN:
        shutil.copy2(os.path.join(src, "Library", "bin", f), os.path.join(dst, f))
    os.makedirs(os.path.join(dst, "DLLs"))
    for f in os.listdir(os.path.join(src, "DLLs")):
        if f.endswith(".pyd") and not f.startswith(DROP_PYD):
            shutil.copy2(os.path.join(src, "DLLs", f), os.path.join(dst, "DLLs", f))
    shutil.copytree(os.path.join(src, "Lib"), os.path.join(dst, "Lib"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for d in DROP_STDLIB:
        shutil.rmtree(os.path.join(dst, "Lib", *d.split("/")), ignore_errors=True)
    os.makedirs(os.path.join(dst, "Lib", "site-packages"))
    for d in TCL_DIRS:
        p = os.path.join(src, "Library", "lib", d)
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(dst, "tcl", d))
    for d in DROP_TCL:
        shutil.rmtree(os.path.join(dst, "tcl", *d.split("/")), ignore_errors=True)


def copy_app(wheels, dst, ico):
    os.makedirs(dst)
    for f in glob.glob(os.path.join(ROOT, "app", "*.py")):                # the engine, window and shared code
        if os.path.basename(f) != "gui.py":                               # (gui.py starts the Mac app)
            shutil.copy2(f, dst)
    shutil.copytree(os.path.join(ROOT, "app", "fonts"), os.path.join(dst, "fonts"))
    for f in glob.glob(os.path.join(WIN, "app", "*.py")):
        shutil.copy2(f, dst)
    shutil.copy2(ico, os.path.join(dst, "StageChart.ico"))
    vendor = os.path.join(dst, "vendor")
    os.makedirs(vendor)
    for w in glob.glob(os.path.join(wheels, "*.whl")):
        if os.path.basename(w).lower().startswith("pillow"):
            continue                          # reportlab's optional Pillow import uses the stub below
        zipfile.ZipFile(w).extractall(vendor)
    for p in glob.glob(os.path.join(vendor, "*.dist-info")) + glob.glob(os.path.join(vendor, "*.data")):
        shutil.rmtree(p)
    shutil.copytree(os.path.join(ROOT, "tools", "pil_stub"), os.path.join(vendor, "PIL"))
    shutil.rmtree(os.path.join(vendor, "reportlab", "fonts"), ignore_errors=True)
    os.makedirs(os.path.join(vendor, "reportlab", "fonts"))
    dnd = os.path.join(vendor, "tkinterdnd2", "tkdnd")
    if os.path.isdir(dnd):                    # keep only the Windows builds of tkdnd
        for d in os.listdir(dnd):
            if os.path.isdir(os.path.join(dnd, d)) and d not in ("win-x64", "win-arm64"):
                shutil.rmtree(os.path.join(dnd, d))
    shutil.rmtree(os.path.join(vendor, "tkinterdnd2", "__pyinstaller"), ignore_errors=True)
    for p in glob.glob(os.path.join(vendor, "**", "__pycache__"), recursive=True):
        shutil.rmtree(p, ignore_errors=True)


def precompile(paths):
    py312 = shutil.which("python3.12")
    if not py312:
        print("python3.12 not found: skipping precompile (first start will be a little slower)")
        return
    for p in paths:
        subprocess.call([py312, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
                         "-x", r"[\\/](test|tests|lib2to3)[\\/]", p])


# DLLs every Windows 10/11 PC has; anything else a bundled DLL imports must be in the bundle.
SYSTEM_DLLS = {
    "kernel32", "user32", "gdi32", "advapi32", "shell32", "ole32", "oleaut32", "comctl32", "comdlg32", "imm32",
    "ws2_32", "bcrypt", "bcryptprimitives", "crypt32", "version", "winmm", "propsys", "rpcrt4", "iphlpapi",
    "netapi32", "userenv", "ntdll", "msvcrt", "shlwapi", "uxtheme", "secur32", "dwmapi", "setupapi", "winspool",
    "mswsock", "psapi", "dbghelp", "cabinet", "msi", "wtsapi32", "pathcch", "ucrtbase", "powrprof", "cfgmgr32",
}
OBJDUMP = "x86_64-w64-mingw32-objdump"


def check_imports(folder):
    """Fail the build if a bundled .exe/.dll/.pyd needs a DLL that is neither bundled nor part of Windows.

    Wine provides some DLLs (zlib1.dll, for one) that a real PC doesn't, so a Wine test can't catch this.
    """
    if not shutil.which(OBJDUMP):
        print("objdump not found: skipping the DLL import check")
        return
    pe, have = [], set()
    for dirpath, dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".dll", ".pyd", ".exe")):
                pe.append(os.path.join(dirpath, f))
                if f.lower().endswith(".dll"):
                    have.add(f.lower())
    missing = {}
    for p in pe:
        out = subprocess.run([OBJDUMP, "-p", p], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "DLL Name:" in line:
                dll = line.split("DLL Name:")[1].strip().lower()
                stem = dll[:-4] if dll.endswith(".dll") else dll
                if dll in have or stem in SYSTEM_DLLS or dll.startswith(("api-ms-win-", "ext-ms-")):
                    continue
                missing.setdefault(dll, []).append(os.path.relpath(p, folder))
    if missing:
        raise SystemExit("Missing DLLs in the bundle:\n" +
                         "\n".join(f"  {d} (needed by {', '.join(v[:3])})" for d, v in sorted(missing.items())))
    print(f"DLL import check: {len(pe)} files OK")


def zip_dir(folder, zpath):
    if os.path.exists(zpath):
        os.remove(zpath)
    base = os.path.dirname(folder)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for dirpath, dirs, files in os.walk(folder):
            dirs.sort()
            for f in sorted(files):
                p = os.path.join(dirpath, f)
                zf.write(p, os.path.relpath(p, base))


def build(runtime, wheels, out_dir):
    folder = os.path.join(out_dir, "Stage Chart")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    ico = os.path.join(out_dir, "StageChart.ico")
    make_icon(ico)
    copy_runtime(runtime, os.path.join(folder, "runtime"))
    copy_app(wheels, os.path.join(folder, "app"), ico)
    build_launcher(os.path.join(folder, "Stage Chart.exe"), ico)
    shutil.copy2(os.path.join(WIN, "How to install.txt"), os.path.join(folder, "How to install.txt"))
    precompile([os.path.join(folder, "runtime", "Lib"), os.path.join(folder, "app")])
    check_imports(folder)
    os.remove(ico)
    return folder


if __name__ == "__main__":
    rt, wh, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    f = build(rt, wh, out)
    if len(sys.argv) > 4:
        zip_dir(f, sys.argv[4])
        print(sys.argv[4])
    else:
        print(f)
