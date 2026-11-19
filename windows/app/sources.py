"""Where charts come from. Each source is a panel in the window that ends by calling app.submit().

Today there is one source, local PDF files. A Planning Center source can be added later as another
class here (sign in, pick a service plan, download each song's chart PDF to a temp folder, then
app.submit(paths, labels=song titles, origin="planning_center")) and listed in SOURCES. With more
than one source, the window shows them as tabs.
"""
import os
import tkinter as tk
from tkinter import filedialog, ttk


class Source:
    title = ""

    def build(self, parent, app):
        """Return a ttk.Frame for this source. `app` is the StageChartWindow."""
        raise NotImplementedError


class FilesSource(Source):
    title = "PDF files"

    def build(self, parent, app):
        f = ttk.Frame(parent, padding=(0, 4))
        drop = tk.Frame(f, bg=app.colors["drop"], highlightthickness=2,
                        highlightbackground=app.colors["drop_border"], cursor="hand2")
        drop.pack(fill="x", ipady=14)
        msg = "Drop chord chart PDFs here" if app.dnd_ok else "Choose chord chart PDFs to convert"
        tk.Label(drop, text=msg, font=app.fonts["drop"], bg=app.colors["drop"],
                 fg=app.colors["text"]).pack(pady=(10, 4))
        ttk.Button(drop, text="Choose PDFs…", command=lambda: self.choose(app),
                   style="Accent.TButton").pack(pady=(2, 10))
        for w in (drop,) + tuple(drop.winfo_children()):
            if isinstance(w, tk.Label) or w is drop:
                w.bind("<Button-1>", lambda e: self.choose(app))
        app.register_drop_target(drop)
        return f

    def choose(self, app):
        start = app.settings.get("last_open_dir") or os.path.expanduser("~")
        paths = filedialog.askopenfilenames(parent=app.root, title="Choose chord chart PDFs",
                                            initialdir=start if os.path.isdir(start) else None,
                                            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if paths:
            app.settings["last_open_dir"] = os.path.dirname(paths[0])
            app.settings.save()
            app.submit(list(paths))


SOURCES = [FilesSource()]
