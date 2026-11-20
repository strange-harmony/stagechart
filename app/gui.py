"""Stage Chart for Mac. The window itself (layout B2) is window.py, shared with the Windows app.

Started by the app bundle as:  python3.12 app/gui.py [files...]  (files dropped on the Dock icon arrive as
an "open documents" event too). If Tk can't start, it falls back to plain macOS dialogs.
"""
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))
sys.path.insert(0, HERE)

import stagechart  # noqa: E402

LOG = os.path.expanduser("~/Library/Logs/Stage Chart.log")


def log_error(text):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def convert_one(path):
    """Returns (ok, output_path_or_None, lines)."""
    try:
        out, summary = stagechart.convert(path)
        return True, out, summary
    except Exception as e:
        log_error(f"{path}\n{traceback.format_exc()}")
        name = e.__class__.__name__
        if "Password" in name or "Encrypt" in name:
            msg = "The PDF is password-protected."
        elif "Syntax" in name or "No /Root" in str(e):
            msg = "The file isn't a readable PDF."
        else:
            msg = str(e) or name
        return False, None, [f"{os.path.basename(path)}: couldn't convert. {msg}"]


# --------------------------------------------------------------------------------------------
# Fallback without Tk: native macOS dialogs through osascript
# --------------------------------------------------------------------------------------------
def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def run_dialogs(files):
    if not files:
        res = osa('set fs to choose file with prompt "Choose chord chart PDFs" of type {"com.adobe.pdf"} '
                  'with multiple selections allowed\nset out to ""\nrepeat with f in fs\n'
                  'set out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
        files = [l for l in res.splitlines() if l.strip()]
    if not files:
        return
    lines, outs = [], []
    for f in files:
        ok, out, summary = convert_one(f)
        lines += summary
        if out:
            outs.append(out)
    text = "\n".join(lines).replace('"', "'")
    osa(f'display dialog "{text}" with title "Stage Chart" buttons {{"OK"}} default button "OK"')
    if outs:
        subprocess.run(["open", "-R", outs[-1]])


class MacPlatform:
    name = "mac"
    file_manager = "Finder"

    def __init__(self):
        self.log_error = log_error
        self.log_path = LOG

    def make_root(self):
        import tkinter as tk
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            return TkinterDnD.Tk(), DND_FILES
        except Exception:
            log_error("in-window drag and drop unavailable (Dock drops still work):\n" + traceback.format_exc())
            return tk.Tk(), None

    def open_file(self, path):
        subprocess.run(["open", path])

    def show_in_folder(self, path):
        subprocess.run(["open", "-R", path])

    def setup(self, win):
        import tkinter as tk
        import window
        root = win.root
        # files dropped on the app or Dock icon arrive as an "open documents" event
        try:
            root.createcommand("::tk::mac::OpenDocument", lambda *args: win.submit(list(args)))
        except Exception:
            pass
        try:
            root.createcommand("tk::mac::Quit", root.destroy)
            root.createcommand("tk::mac::ShowPreferences", win.open_settings)
        except Exception:
            pass
        window.start_updates(win)
        menubar = tk.Menu(root)
        app_menu = tk.Menu(menubar, name="apple", tearoff=0)
        app_menu.add_command(label="About Stage Chart", command=win.open_about)
        app_menu.add_command(label="Check for Updates…", command=lambda: win.updates and win.updates.check_now())
        app_menu.add_separator()
        menubar.add_cascade(menu=app_menu)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Choose PDFs…", accelerator="Command-O", command=win.choose_files)
        menubar.add_cascade(label="File", menu=file_menu)
        root.bind_all("<Command-o>", lambda e: win.choose_files())
        root.config(menu=menubar)

    def settings_extras(self, win, dialog):
        pass

    def first_run(self, win):
        pass


def run_window(initial):
    import window
    window.StageChartWindow(MacPlatform(), initial).run()


def main():
    files = [a for a in sys.argv[1:] if not a.startswith("-psn_") and os.path.isfile(a)]
    try:
        import tkinter  # noqa: F401
        run_window(files)
    except Exception:
        log_error(traceback.format_exc())
        run_dialogs(files)


if __name__ == "__main__":
    main()
