"""Stage Chart for Windows. The window itself (layout B2) is window.py, shared with the Mac app.

Started by "Stage Chart.exe" as:  runtime\\pythonw.exe -B -E -s app\\gui_win.py [files...]
Files dropped on the .exe or sent with right-click > Send to > Stage Chart arrive as arguments.
"""
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))
sys.path.insert(0, HERE)
# Running from the repository (windows/app/gui_win.py): the shared code is in ../../app
_repo_app = os.path.join(os.path.dirname(os.path.dirname(HERE)), "app")
if not os.path.exists(os.path.join(HERE, "stagechart.py")) and os.path.isdir(_repo_app):
    sys.path.insert(1, _repo_app)
    sys.path.insert(2, os.path.join(_repo_app, "vendor"))

# Bundled Tcl/Tk lives in runtime\tcl; point Tk at it before tkinter loads.
_rt = os.path.dirname(os.path.abspath(sys.executable))
for _var, _sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    _p = os.path.join(_rt, "tcl", _sub)
    if os.path.isdir(_p):
        os.environ[_var] = _p

import settings as settings_mod  # noqa: E402
import winplatform as wp  # noqa: E402

LOG = os.path.join(settings_mod.log_dir(), "Stage Chart.log")


def log_error(text):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except OSError:
        pass


class WindowsPlatform:
    name = "windows"
    file_manager = "File Explorer"

    def __init__(self):
        self.log_error = log_error
        self.log_path = LOG

    def make_root(self):
        import tkinter as tk
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            return TkinterDnD.Tk(), DND_FILES
        except Exception:
            log_error("Drag and drop unavailable:\n" + traceback.format_exc())
            return tk.Tk(), None

    def open_file(self, path):
        wp.open_file(path)

    def show_in_folder(self, path):
        wp.show_in_folder(path)

    def setup(self, win):
        import window
        ico = os.path.join(HERE, "StageChart.ico")
        if os.path.exists(ico) and wp.IS_WIN:
            try:
                win.root.iconbitmap(default=ico)
            except Exception:
                pass
        win.root.bind_all("<Control-o>", lambda e: win.choose_files())
        win.root.bind_all("<Control-comma>", lambda e: win.open_settings())
        win.root.bind_all("<F1>", lambda e: win.open_about())
        window.start_updates(win)

    def settings_extras(self, win, dialog):
        """Shortcuts (Desktop, Start menu, right-click Send to) in the Settings window."""
        if not wp.IS_WIN:
            return
        from widgets import Pill, label
        L = win.look
        box = dialog.section("Shortcuts")
        label(box, L, "Put Stage Chart on the Desktop and Start menu, and in the right-click “Send to” menu "
                      "for PDFs.", size=13, color="muted", wrap=440).pack(fill="x", pady=(0, L.px(10)))
        import tkinter as tk
        from widgets import T
        row = tk.Frame(box, bg=T["card"])
        row.pack(fill="x")
        Pill(row, L, "Add shortcuts", lambda: self.add_shortcuts(win), kind="outline", size=13, height=36,
             padx=14, weight="semibold").pack(side="left")
        Pill(row, L, "Remove shortcuts", lambda: self.remove_shortcuts(win), kind="outline", size=13, height=36,
             padx=14, weight="semibold").pack(side="left", padx=(win.look.px(10), 0))

    def add_shortcuts(self, win, quiet_ok=False):
        from tkinter import messagebox
        made, errors = wp.make_shortcuts()
        if errors:
            log_error("shortcuts:\n" + "\n".join(errors))
            messagebox.showwarning("Stage Chart", "Some shortcuts couldn't be made:\n\n" + "\n".join(errors),
                                   parent=win.root)
        elif made and not quiet_ok:
            messagebox.showinfo("Stage Chart", "Added Stage Chart to your " + ", ".join(made) + ".", parent=win.root)

    def remove_shortcuts(self, win):
        from tkinter import messagebox
        wp.remove_shortcuts()
        messagebox.showinfo("Stage Chart", "Removed the Desktop, Start menu and Send to shortcuts.", parent=win.root)

    def first_run(self, win):
        from tkinter import messagebox
        s = win.settings
        if s.get("asked_shortcuts") or not wp.IS_WIN or not os.path.exists(wp.app_exe()):
            return
        s["asked_shortcuts"] = True
        s.save()
        if messagebox.askyesno(
                "Stage Chart",
                "Add Stage Chart to your Desktop and Start menu, and to the right-click \"Send to\" menu "
                "for PDFs?\n\nYou can change this later in Settings.", parent=win.root):
            self.add_shortcuts(win, quiet_ok=True)


def main():
    files = [os.path.abspath(a) for a in sys.argv[1:] if os.path.exists(a)]
    wp.enable_dpi_awareness()
    wp.set_app_id()
    try:
        import window
        window.StageChartWindow(WindowsPlatform(), files).run()
    except Exception:
        log_error(traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"Stage Chart couldn't start.\n\nDetails are in:\n{LOG}",
                                             "Stage Chart", 0x10)
        except Exception:
            raise


if __name__ == "__main__":
    main()
