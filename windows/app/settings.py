"""Small JSON settings file in %APPDATA%\\Stage Chart (or ~/.config/stage-chart elsewhere).

Planning Center settings can live here later (organization, last service type). Secrets such as
an access token belong in Windows Credential Manager, not in this file.
"""
import json
import os
import sys


def data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Stage Chart")
    return os.path.join(os.path.expanduser("~"), ".config", "stage-chart")


def log_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Stage Chart")
    return data_dir()


PATH = os.path.join(data_dir(), "settings.json")
DEFAULTS = {
    "save_mode": "beside",      # "beside" the original, or "folder"
    "save_folder": "",
    "asked_shortcuts": False,
}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            with open(PATH, encoding="utf-8") as fh:
                self.update(json.load(fh))
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(PATH), exist_ok=True)
            tmp = PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dict(self), fh, indent=2)
            os.replace(tmp, PATH)
        except OSError:
            pass
