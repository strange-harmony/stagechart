"""Stage Chart for Windows: pick or drop chord chart PDFs and save stage charts.

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
# Running from the repository (windows/app/gui_win.py): the shared engine is in ../../app
_repo_app = os.path.join(os.path.dirname(os.path.dirname(HERE)), "app")
if not os.path.exists(os.path.join(HERE, "stagechart.py")) and os.path.isdir(_repo_app):
    sys.path.insert(1, _repo_app)

# Bundled Tcl/Tk lives in runtime\tcl; point Tk at it before tkinter loads.
_rt = os.path.dirname(os.path.abspath(sys.executable))
for _var, _sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    _p = os.path.join(_rt, "tcl", _sub)
    if os.path.isdir(_p):
        os.environ[_var] = _p

import jobs  # noqa: E402
import settings as settings_mod  # noqa: E402
import winplatform as wp  # noqa: E402

VERSION = "1.0"
LOG = os.path.join(settings_mod.log_dir(), "Stage Chart.log")


def log_error(text):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except OSError:
        pass


class StageChartWindow:
    colors = {"bg": "#f5f5f7", "text": "#1d1d1f", "muted": "#515154", "ok": "#1a7f37", "bad": "#c62828",
              "drop": "#ffffff", "drop_border": "#c7c7cc", "drop_hot": "#e8f0fe", "drop_hot_border": "#2f6fdf"}

    def __init__(self, initial_files):
        import tkinter as tk
        from tkinter import font, ttk

        from sources import SOURCES

        self.tk = tk
        self.settings = settings_mod.Settings()
        self.last_out = None
        self.dnd_ok = False
        self._dnd_files = None

        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            self.root = TkinterDnD.Tk()
            self._dnd_files = DND_FILES
            self.dnd_ok = True
        except Exception:
            log_error("Drag and drop unavailable:\n" + traceback.format_exc())
            self.root = tk.Tk()
        root = self.root
        root.title("Stage Chart")
        root.geometry("620x560")
        root.minsize(520, 460)
        root.configure(bg=self.colors["bg"])
        ico = os.path.join(HERE, "StageChart.ico")
        if os.path.exists(ico) and wp.IS_WIN:
            try:
                root.iconbitmap(default=ico)
            except Exception:
                pass

        family = "Segoe UI" if wp.IS_WIN else "DejaVu Sans"
        self.fonts = {"title": font.Font(family=family, size=18, weight="bold"),
                      "body": font.Font(family=family, size=10),
                      "drop": font.Font(family=family, size=12),
                      "log": font.Font(family=family, size=10)}
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"],
                        font=self.fonts["body"])
        style.configure("TRadiobutton", background=self.colors["bg"], font=self.fonts["body"])
        style.configure("TButton", font=self.fonts["body"], padding=(10, 4))
        style.configure("Accent.TButton", font=self.fonts["drop"], padding=(14, 6))

        self._menu()

        outer = ttk.Frame(root, padding=(18, 12, 18, 12))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Stage Chart", font=self.fonts["title"]).pack(anchor="w")
        ttk.Label(outer, foreground=self.colors["muted"],
                  text="Turns a chord chart PDF into a light, two-column, 17pt stage chart in the same key.\n"
                       "The original PDF is never changed.").pack(anchor="w", pady=(0, 10))

        # ---- sources (one panel today; tabs once Planning Center is added)
        if len(SOURCES) == 1:
            SOURCES[0].build(outer, self).pack(fill="x")
        else:
            nb = ttk.Notebook(outer)
            nb.pack(fill="x")
            for s in SOURCES:
                nb.add(s.build(nb, self), text=s.title)

        # ---- where to save
        save = ttk.Frame(outer)
        save.pack(fill="x", pady=(12, 0))
        ttk.Label(save, text="Save stage charts:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.save_mode = tk.StringVar(value=self.settings.get("save_mode", "beside"))
        ttk.Radiobutton(save, text="Next to the original", value="beside", variable=self.save_mode,
                        command=self._save_mode_changed).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(save, text="In this folder:", value="folder", variable=self.save_mode,
                        command=self._save_mode_changed).grid(row=1, column=1, sticky="w")
        self.folder_label = ttk.Label(save, text="", foreground=self.colors["muted"])
        self.folder_label.grid(row=1, column=2, sticky="w", padx=(4, 8))
        ttk.Button(save, text="Change…", command=self._pick_folder).grid(row=1, column=3, sticky="e")
        save.columnconfigure(2, weight=1)
        self._show_folder()

        # ---- log
        logf = ttk.Frame(outer)
        logf.pack(fill="both", expand=True, pady=(12, 6))
        self.logbox = tk.Text(logf, height=8, wrap="word", font=self.fonts["log"], relief="flat",
                              bg="white", fg=self.colors["text"], padx=10, pady=8, highlightthickness=1,
                              highlightbackground="#d2d2d7")
        sb = ttk.Scrollbar(logf, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.logbox.tag_configure("ok", foreground=self.colors["ok"])
        self.logbox.tag_configure("bad", foreground=self.colors["bad"])
        hint = ("Drop PDFs above, click Choose PDFs, or right-click PDFs in File Explorer and use Send to > "
                "Stage Chart.") if self.dnd_ok else "Click Choose PDFs, or drop PDFs onto the Stage Chart icon."
        self.say(hint)
        self.register_drop_target(self.logbox)

        # ---- results
        btns = ttk.Frame(outer)
        btns.pack(fill="x")
        self.open_btn = ttk.Button(btns, text="Open Chart", state="disabled",
                                   command=lambda: self.last_out and wp.open_file(self.last_out))
        self.show_btn = ttk.Button(btns, text="Show in Folder", state="disabled",
                                   command=lambda: self.last_out and wp.show_in_folder(self.last_out))
        self.open_btn.pack(side="left")
        self.show_btn.pack(side="left", padx=6)

        self.queue = jobs.ConversionQueue(self._job_started, self._job_done, log_error)
        self._pump()
        if initial_files:
            root.after(200, lambda: self.submit(initial_files))
        root.after(600, self._first_run)

    # ------------------------------------------------------------------ public, used by sources
    def say(self, text, tag=None):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n", tag)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def out_dir(self):
        if self.save_mode.get() == "folder" and os.path.isdir(self.settings.get("save_folder", "")):
            return self.settings["save_folder"]
        return None

    def submit(self, paths, labels=None, origin="file"):
        """Queue PDFs for conversion. Sources call this; labels are optional display names."""
        labels = labels or [""] * len(paths)
        todo = []
        for p, lab in zip(paths, labels):
            if os.path.isdir(p):
                self.say(f"✗ {os.path.basename(p)}: that's a folder. Choose the PDFs inside it.", "bad")
            elif not p.lower().endswith(".pdf"):
                self.say(f"✗ {os.path.basename(p)}: only PDF files can be converted.", "bad")
            else:
                todo.append(jobs.Job(p, self.out_dir(), lab, origin))
        self.queue.submit(todo)

    def register_drop_target(self, widget):
        if not self.dnd_ok:
            return
        try:
            widget.drop_target_register(self._dnd_files)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            if "highlightbackground" in widget.keys() and not isinstance(widget, self.tk.Text):
                widget.dnd_bind("<<DropEnter>>", lambda e, w=widget: self._hot(w, True))
                widget.dnd_bind("<<DropLeave>>", lambda e, w=widget: self._hot(w, False))
        except Exception:
            log_error("drop target:\n" + traceback.format_exc())

    # ------------------------------------------------------------------ internals
    def _hot(self, w, on):
        c = self.colors
        try:
            w.configure(highlightbackground=c["drop_hot_border" if on else "drop_border"],
                        bg=c["drop_hot" if on else "drop"])
            for ch in w.winfo_children():
                if isinstance(ch, self.tk.Label):
                    ch.configure(bg=c["drop_hot" if on else "drop"])
        except Exception:
            pass
        return "copy"

    def _on_drop(self, event):
        paths = [p for p in self.root.tk.splitlist(event.data) if p]
        self.submit(paths)
        try:
            self._hot(event.widget, False)
        except Exception:
            pass
        return "copy"

    def _job_started(self, job):
        self.say(f"Converting {job.label or os.path.basename(job.path)} …")

    def _job_done(self, res):
        if res.ok:
            self.say(f"✓ Saved “{os.path.basename(res.out)}”", "ok")
            for s in res.lines:
                self.say("    " + s)
            self.last_out = res.out
            self.open_btn.configure(state="normal")
            self.show_btn.configure(state="normal")
        else:
            for s in res.lines:
                self.say("✗ " + s, "bad")

    def _pump(self):
        self.queue.drain()
        self.root.after(100, self._pump)

    def _show_folder(self):
        f = self.settings.get("save_folder", "")
        self.folder_label.configure(text=f if f else "(none chosen)")

    def _save_mode_changed(self):
        if self.save_mode.get() == "folder" and not os.path.isdir(self.settings.get("save_folder", "")):
            if not self._pick_folder():
                self.save_mode.set("beside")
        self.settings["save_mode"] = self.save_mode.get()
        self.settings.save()

    def _pick_folder(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(parent=self.root, title="Save stage charts in this folder",
                                    initialdir=self.settings.get("save_folder") or os.path.expanduser("~"))
        if not d:
            return False
        self.settings["save_folder"] = os.path.normpath(d)
        self.save_mode.set("folder")
        self.settings["save_mode"] = "folder"
        self.settings.save()
        self._show_folder()
        return True

    def _menu(self):
        tk = self.tk
        bar = tk.Menu(self.root)
        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="Add shortcuts (Desktop, Start menu, Send to)", command=self._add_shortcuts)
        m.add_command(label="Remove shortcuts", command=self._remove_shortcuts)
        m.add_separator()
        m.add_command(label="Open log folder", command=lambda: self._open_dir(os.path.dirname(LOG)))
        m.add_separator()
        m.add_command(label="Exit", command=self.root.destroy)
        bar.add_cascade(label="Options", menu=m)
        h = tk.Menu(bar, tearoff=0)
        h.add_command(label="About Stage Chart", command=self._about)
        bar.add_cascade(label="Help", menu=h)
        self.root.config(menu=bar)

    def _open_dir(self, d):
        os.makedirs(d, exist_ok=True)
        wp.open_file(d)

    def _about(self):
        from tkinter import messagebox
        messagebox.showinfo("About Stage Chart",
                            f"Stage Chart {VERSION} for Windows\n\n"
                            "Light mode, two columns, 17pt lyrics, original key, page count matched where "
                            "possible, repeats shown once with ×2, bridges printed in order with cues, "
                            "slash chords like D/F#.\n\nFont: Carlito (SIL Open Font License).",
                            parent=self.root)

    def _add_shortcuts(self, quiet_ok=False):
        from tkinter import messagebox
        if not wp.IS_WIN:
            return
        made, errors = wp.make_shortcuts()
        if errors:
            log_error("shortcuts:\n" + "\n".join(errors))
            messagebox.showwarning("Stage Chart", "Some shortcuts couldn't be made:\n\n" + "\n".join(errors),
                                   parent=self.root)
        elif made and not quiet_ok:
            messagebox.showinfo("Stage Chart", "Added Stage Chart to your " + ", ".join(made) + ".",
                                parent=self.root)
        if made:
            self.say("Added shortcuts: " + ", ".join(made) + ".")

    def _remove_shortcuts(self):
        wp.remove_shortcuts()
        self.say("Removed the Desktop, Start menu and Send to shortcuts.")

    def _first_run(self):
        from tkinter import messagebox
        if self.settings.get("asked_shortcuts") or not wp.IS_WIN or not os.path.exists(wp.app_exe()):
            return
        self.settings["asked_shortcuts"] = True
        self.settings.save()
        if messagebox.askyesno(
                "Stage Chart",
                "Add Stage Chart to your Desktop and Start menu, and to the right-click \"Send to\" menu "
                "for PDFs?\n\nYou can change this later under Options.", parent=self.root):
            self._add_shortcuts(quiet_ok=True)

    def run(self):
        self.root.lift()
        self.root.focus_force()
        self.root.mainloop()


def main():
    files = [os.path.abspath(a) for a in sys.argv[1:] if os.path.exists(a)]
    wp.enable_dpi_awareness()
    wp.set_app_id()
    try:
        StageChartWindow(files).run()
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
