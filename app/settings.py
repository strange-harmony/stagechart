"""Small JSON settings file, shared by the Mac and Windows apps.

  Windows: %APPDATA%\\Stage Chart\\settings.json      Mac: ~/Library/Application Support/Stage Chart
  Elsewhere: ~/.config/stage-chart

The Planning Center token is not kept here: see secrets_store.py.
"""
import json
import os
import sys


def data_dir():
    if os.environ.get("STAGECHART_DATA_DIR"):           # tests use a throwaway folder
        return os.environ["STAGECHART_DATA_DIR"]
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Stage Chart")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Stage Chart")
    return os.path.join(os.path.expanduser("~"), ".config", "stage-chart")


def log_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Stage Chart")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Logs")
    return data_dir()


def documents_dir():
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0005, None, 0, buf) == 0:   # CSIDL_PERSONAL
                return buf.value
        except Exception:
            pass
    d = os.path.join(os.path.expanduser("~"), "Documents")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def path():
    return os.path.join(data_dir(), "settings.json")


DEFAULTS = {
    "save_mode": "beside",        # dropped PDFs: "beside" the original, or "folder"
    "save_folder": "",
    "asked_shortcuts": False,     # Windows: asked once about Desktop / Start menu / Send to shortcuts
    "last_open_dir": "",
    "pc_folder": "",              # where Planning Center sets go ("" = Documents/Stage Charts)
    "pc_service_types": [],       # ids to show; [] = all
    "pc_combined": True,          # also make one PDF for the whole set
}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            with open(path(), encoding="utf-8") as fh:
                self.update(json.load(fh))
        except (OSError, ValueError):
            pass

    def pc_folder(self):
        f = self.get("pc_folder") or ""
        return f if f else os.path.join(documents_dir(), "Stage Charts")

    def save(self):
        try:
            p = path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dict(self), fh, indent=2)
            os.replace(tmp, p)
        except OSError:
            pass
