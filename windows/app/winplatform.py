"""Windows integration: opening files, Explorer, shortcuts (Desktop, Start menu, Send To)."""
import os
import subprocess
import sys

IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def app_exe():
    """The 'Stage Chart.exe' launcher next to the runtime folder (what shortcuts should point at)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "Stage Chart.exe")


def open_file(path):
    if IS_WIN:
        os.startfile(path)  # noqa: S606  (opens in the default PDF viewer)
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_folder(path):
    if IS_WIN:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def _shell_folder(name):
    """Desktop / Programs (Start menu) / SendTo via the Windows API, with fallbacks."""
    csidl = {"Desktop": 0x0010, "Programs": 0x0002, "SendTo": 0x0009}[name]
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
            return buf.value
    except Exception:
        pass
    appdata = os.environ.get("APPDATA", "")
    return {"Desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
            "Programs": os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"),
            "SendTo": os.path.join(appdata, "Microsoft", "Windows", "SendTo")}[name]


SHORTCUT_PLACES = (("Desktop", "Desktop"), ("Programs", "Start menu"), ("SendTo", "right-click Send to menu"))


def shortcut_path(place):
    return os.path.join(_shell_folder(place), "Stage Chart.lnk")


def make_shortcuts():
    """Create the three shortcuts with PowerShell's WScript.Shell. Returns (made, errors)."""
    exe = app_exe()
    made, errors = [], []
    for place, label in SHORTCUT_PLACES:
        lnk = shortcut_path(place)
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:SC_LNK);"
              "$s.TargetPath=$env:SC_EXE;$s.WorkingDirectory=$env:SC_DIR;"
              "$s.IconLocation=$env:SC_EXE+',0';$s.Description='Make stage charts from chord chart PDFs';"
              "$s.Save()")
        env = dict(os.environ, SC_LNK=lnk, SC_EXE=exe, SC_DIR=os.path.dirname(exe))
        try:
            os.makedirs(os.path.dirname(lnk), exist_ok=True)
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-Command", ps], env=env, capture_output=True, text=True,
                               creationflags=NO_WINDOW if IS_WIN else 0, timeout=60)
            if r.returncode == 0 and os.path.exists(lnk):
                made.append(label)
            else:
                errors.append(f"{label}: {(r.stderr or r.stdout).strip()[:200]}")
        except Exception as e:
            errors.append(f"{label}: {e}")
    return made, errors


def remove_shortcuts():
    for place, _ in SHORTCUT_PLACES:
        try:
            os.remove(shortcut_path(place))
        except OSError:
            pass


def enable_dpi_awareness():
    """Sharp text on high-DPI screens (otherwise Windows blurs the whole window)."""
    if not IS_WIN:
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_id():
    """Group the window under its own taskbar icon instead of Python's."""
    if not IS_WIN:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("StageChart.Converter")
    except Exception:
        pass
