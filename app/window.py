"""The Stage Chart window (layout B2), shared by the Mac and Windows apps.

    ┌ Stage Chart ─────────────────────────────────────────── [Settings] ┐
    │ Planning Center card          │ Drop chord charts here            │
    │  next up / selected plan      │  Choose PDFs…  Import from PC     │
    │  Convert this set + calendar  │                                   │
    ├───────────────────────────────┼───────────────────────────────────┤
    │ Last finished (page preview)  │ This batch (one row per chart)    │
    └───────────────────────────────┴───────────────────────────────────┘

The platform files (gui.py on the Mac, windows/app/gui_win.py) start it with a Platform object that knows
how to open files and folders, and add their own extras (Dock drops, shortcuts, menus).
Charts are made by the unchanged engine (stagechart.convert) through jobs.ConversionQueue; Planning Center
is read through pco.py. Charts are never transposed: with a plan, Stage Chart downloads the chart for the
key the song is scheduled in, and flags it if the chart's key doesn't match the plan.
"""
import calendar
import datetime as dt
import os
import threading
import tkinter as tk
import tkinter.font  # noqa: F401  (credit() underlines the link)
import traceback
from tkinter import filedialog

import jobs
import pco
import secrets_store
import settings as settings_mod
from widgets import (T, Badge, Bar, Calendar, ChartPreview, Dot, Field, Look, Panel, Pill, Scroller,
                     Toggle, dark_title_bar, label, round_rect, separator)

LEFT_W = 290            # the narrow column, as in the mockup
GAP = 20


class Platform:
    """What differs between the Mac and Windows apps. The defaults work anywhere for testing."""
    name = "other"
    file_manager = "folder"                     # "Finder" / "File Explorer"

    def __init__(self, log_error=lambda text: None, log_path=""):
        self.log_error = log_error
        self.log_path = log_path

    def make_root(self):
        """Returns (root, drop_type). drop_type is tkinterdnd2's DND_FILES when drag and drop works."""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            return TkinterDnD.Tk(), DND_FILES
        except Exception:
            return tk.Tk(), None

    def open_file(self, path):
        import subprocess
        subprocess.Popen(["xdg-open", path])

    def show_in_folder(self, path):
        import subprocess
        subprocess.Popen(["xdg-open", os.path.dirname(path)])

    def setup(self, win):
        """Menus, icons, platform events. Called once the window is built."""

    def settings_extras(self, win, parent):
        """Extra rows for the Settings window (Windows: shortcuts)."""

    def first_run(self, win):
        """Called shortly after the window opens."""


class Row:
    """One line in "This batch"."""

    def __init__(self, win, name, detail, state="waiting"):
        L = win.look
        self.win, self.name = win, name
        self.out = None
        self.state = state
        self.frame = tk.Frame(win.batch.inner, bg=T["card"])
        inner = tk.Frame(self.frame, bg=T["card"])
        inner.pack(fill="x", padx=L.px(20), pady=L.px(12))
        thumb = tk.Canvas(inner, width=L.px(34), height=L.px(44), bg=T["card"], highlightthickness=0)
        round_rect(thumb, 0, 0, L.px(34), L.px(44), L.px(3), fill="#f4f5fb", outline="#f4f5fb")
        for i, y in enumerate((9, 15, 22, 28, 35)):
            thumb.create_line(L.px(6), L.px(y), L.px(28 - (i % 2) * 8), L.px(y),
                              fill="#c4c6d6" if i % 2 else "#8b7cf6", width=max(1, L.px(2)))
        thumb.pack(side="left", padx=(0, L.px(14)))
        self.thumb = thumb
        text = tk.Frame(inner, bg=T["card"])
        text.pack(side="left", fill="x", expand=True)
        self.name_lab = label(text, L, name, size=14, weight="semibold")
        self.name_lab.pack(fill="x")
        self.detail_lab = label(text, L, detail, size=13, color="muted")
        self.detail_lab.pack(fill="x", pady=(L.px(2), 0))
        text.bind("<Configure>", lambda e: (self.name_lab.configure(wraplength=max(80, e.width)),
                                            self.detail_lab.configure(wraplength=max(80, e.width))))
        self.bar = Bar(text, L)
        self.open_btn = Pill(inner, L, "Open", self._open, kind="outline", size=13, height=36, padx=12, radius=8,
                             weight="semibold")
        self.badge = Badge(inner, L)
        self.open_btn.pack(side="right", padx=(L.px(10), 0))
        self.badge.pack(side="right")
        self.open_btn.pack_forget()
        separator(self.frame, L, "row_line").pack(fill="x", side="bottom")
        self.frame.pack(fill="x")
        win.bind_wheel(self.frame)
        self.set(state, detail)

    def set(self, state, detail=None, out=None):
        self.state = state
        if detail is not None:
            self.detail_lab.configure(text=detail)
        if out:
            self.out = out
        self.badge.set(state)
        if state in ("busy", "download"):
            self.bar.pack(fill="x", anchor="w", pady=(self.win.look.px(8), 0))
            self.bar.start()
        else:
            self.bar.stop()
            self.bar.pack_forget()
        if self.out and state in ("done", "check"):
            self.open_btn.pack(side="right", padx=(self.win.look.px(10), 0))
            self.badge.pack_forget()
            self.badge.pack(side="right")
        self.win.update_count()

    @property
    def finished(self):
        return self.state in ("done", "check", "bad", "missing")

    def _open(self):
        if self.out:
            self.win.platform.open_file(self.out)

    def destroy(self):
        self.bar.stop()
        self.frame.destroy()


class StageChartWindow:
    def __init__(self, platform, initial_files=(), smoke=False):
        self.platform = platform
        self.log_error = platform.log_error
        self.settings = settings_mod.Settings()
        self.smoke = smoke
        root, self.dnd = platform.make_root()
        self.root = root
        root.title("Stage Chart")
        root.configure(bg=T["bg"])
        self.look = L = Look(root)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(L.px(1180), sw - 40), min(L.px(940), sh - 90)
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        root.minsize(min(L.px(900), sw - 40), min(L.px(560), sh - 90))
        dark_title_bar(root)

        self.rows = []                   # Row, newest last
        self.rows_by_job = {}
        self.sets = {}                   # set_id -> dict, for the combined set PDF
        self.last = None                 # last good jobs.Result
        self.client = None
        self.org = ""
        self.service_types = []
        self.month = (dt.date.today().year, dt.date.today().month)
        self.month_plans = {}            # (y, m) -> {date: [Plan]}
        self.next_plan = None
        self.plan = None                 # selected plan
        self.songs_cache = {}            # plan.id -> [SongItem]
        self.settings_win = None
        self.pc_state = "intro"

        self.queue = jobs.ConversionQueue(self._job_started, self._job_done, self.log_error)
        self._build()
        self._pump()
        platform.setup(self)
        self._wheel_bindings()
        self._start_pc()
        if initial_files:
            root.after(250, lambda: self.submit(list(initial_files)))
        if not smoke:
            root.after(700, lambda: platform.first_run(self))

    # ================================================================== layout
    def _build(self):
        L, root = self.look, self.root
        self.scroll = Scroller(root, L, T["bg"])
        self.scroll.pack(fill="both", expand=True)
        page = tk.Frame(self.scroll.inner, bg=T["bg"])
        page.pack(fill="both", expand=True, padx=L.px(24), pady=(L.px(22), L.px(26)))
        self.page = page

        head = tk.Frame(page, bg=T["bg"])
        head.pack(fill="x", pady=(0, L.px(GAP)))
        label(head, L, "Stage Chart", size=20, weight="bold").pack(side="left")
        Pill(head, L, "Settings", self.open_settings, kind="chrome", size=13, height=40, padx=16,
             weight="semibold").pack(side="right")

        grid = tk.Frame(page, bg=T["bg"])
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, minsize=L.px(LEFT_W), weight=0)
        grid.columnconfigure(1, weight=1, minsize=L.px(520))
        grid.rowconfigure(0, weight=0)
        grid.rowconfigure(1, weight=1)
        g = L.px(GAP)

        # -------- row 1, left: Planning Center
        self.pc_panel = Panel(grid, L, T["card"], T["card_line"], width_px=LEFT_W)
        self.pc_panel.grid(row=0, column=0, sticky="nsew", padx=(0, g), pady=(0, g))
        self._build_pc(self.pc_panel.body)

        # -------- row 1, right: drop zone
        self.drop_panel = Panel(grid, L, T["drop"], T["drop_line"], dash=(6, 4), pad=24, line_w=2)
        self.drop_panel.grid(row=0, column=1, sticky="nsew", pady=(0, g))
        self._build_drop(self.drop_panel.body)

        # -------- row 2, left: last finished
        self.last_panel = Panel(grid, L, T["card"], T["card_line"], width_px=LEFT_W)
        self.last_panel.grid(row=1, column=0, sticky="nsew", padx=(0, g))
        self._build_last(self.last_panel.body)

        # -------- row 2, right: this batch
        self.batch_panel = Panel(grid, L, T["card"], T["card_line"], pad=1)
        self.batch_panel.grid(row=1, column=1, sticky="nsew")
        self._build_batch(self.batch_panel.body)

    # ------------------------------------------------------------------ Planning Center card
    def _build_pc(self, body):
        L = self.look
        self.pc_body = body
        self.pc_frames = {}

        # not connected: intro
        f = tk.Frame(body, bg=T["card"])
        icon = tk.Canvas(f, width=L.px(56), height=L.px(56), bg=T["card"], highlightthickness=0)
        icon.create_oval(0, 0, L.px(56) - 1, L.px(56) - 1, fill=T["chip"], outline=T["chip"])
        c, k = L.px(28), L.px(1)
        icon.create_rectangle(c - 9 * k, c - 7 * k, c + 9 * k, c + 10 * k, outline=T["link"], width=max(2, L.px(2)))
        icon.create_line(c - 9 * k, c - 1 * k, c + 9 * k, c - 1 * k, fill=T["link"], width=max(2, L.px(2)))
        icon.create_line(c - 4 * k, c - 10 * k, c - 4 * k, c - 5 * k, fill=T["link"], width=max(2, L.px(2)))
        icon.create_line(c + 4 * k, c - 10 * k, c + 4 * k, c - 5 * k, fill=T["link"], width=max(2, L.px(2)))
        icon.pack(pady=(L.px(30), L.px(14)))
        label(f, L, "Convert whole sets", size=18, weight="bold", anchor="center").pack()
        label(f, L, "Connect Planning Center to see upcoming services here.", size=14, color="muted",
              wrap=230, justify="center", anchor="center").pack(pady=(L.px(10), L.px(16)))
        Pill(f, L, "Get started", lambda: self._pc_show("form"), kind="light", size=14, height=44).pack(
            pady=(0, L.px(30)))
        self.pc_frames["intro"] = f

        # not connected: token form
        f = tk.Frame(body, bg=T["card"])
        label(f, L, "Connect Planning Center", size=18, weight="bold").pack(fill="x")
        label(f, L, "Paste the two parts of your personal access token.", size=14, color="sub", wrap=250).pack(
            fill="x", pady=(L.px(6), L.px(12)))
        self.f_app = Field(f, L, "Application ID", placeholder="Paste from Planning Center")
        self.f_app.pack(fill="x", pady=(0, L.px(12)))
        self.f_secret = Field(f, L, "Secret", show="•", placeholder="Paste from Planning Center")
        self.f_secret.pack(fill="x", pady=(0, L.px(12)))
        self.form_err = label(f, L, "", size=13, color="text", wrap=250)
        self.form_err.configure(fg=PILL_BAD_FG)
        self.connect_btn = Pill(f, L, "Connect", self._connect, kind="light", size=14, height=44, fill_x=True)
        self.connect_btn.pack(fill="x")
        Pill(f, L, "Cancel", lambda: self._pc_show("intro"), kind="link", size=13, height=36,
             weight="semibold").pack(fill="x")
        separator(f, L).pack(fill="x", pady=(L.px(8), L.px(8)))
        lnk = label(f, L, "Get a personal access token", size=13, color="link", weight="semibold", cursor="hand2")
        lnk.pack(fill="x")
        lnk.bind("<Button-1>", lambda e: self._open_url(pco.TOKEN_PAGE))
        label(f, L, "Saved only on this computer. Dropping PDFs works without it.", size=12, color="dim",
              wrap=250).pack(fill="x", pady=(L.px(4), 0))
        self.f_secret.entry.bind("<Return>", lambda e: self._connect())
        self.pc_frames["form"] = f

        # connected
        f = tk.Frame(body, bg=T["card"])
        top = tk.Frame(f, bg=T["card"])
        top.pack(fill="x")
        self.pc_dot = Dot(top, L, T["ok_dot"])
        self.pc_dot.pack(side="left", padx=(0, L.px(8)))
        label(top, L, "PLANNING CENTER", size=12, color="muted", weight="bold").pack(side="left")
        self.plan_when = label(f, L, "Next up", size=13, color="muted")
        self.plan_when.pack(fill="x", pady=(L.px(12), 0))
        self.plan_date = label(f, L, "", size=18, weight="bold")
        self.plan_date.pack(fill="x", pady=(L.px(2), 0))
        self.plan_info = label(f, L, "", size=14, color="sub", wrap=250)
        self.plan_info.pack(fill="x", pady=(L.px(2), L.px(12)))
        self.convert_set_btn = Pill(f, L, "Convert this set", self.convert_set, kind="light", size=14, height=44,
                                    fill_x=True)
        self.convert_set_btn.pack(fill="x")
        separator(f, L).pack(fill="x", pady=(L.px(14), L.px(10)))
        self.cal = Calendar(f, L, self._month_step, self._pick_day)
        self.cal.pack(fill="x")
        self.pc_frames["connected"] = f

        # loading / problem
        f = tk.Frame(body, bg=T["card"])
        top = tk.Frame(f, bg=T["card"])
        top.pack(fill="x")
        self.msg_dot = Dot(top, L, T["dim"])
        self.msg_dot.pack(side="left", padx=(0, L.px(8)))
        label(top, L, "PLANNING CENTER", size=12, color="muted", weight="bold").pack(side="left")
        self.msg_text = label(f, L, "", size=14, color="sub", wrap=250)
        self.msg_text.pack(fill="x", pady=(L.px(16), L.px(14)))
        self.msg_btn = Pill(f, L, "Try again", self._load_pc, kind="outline", size=13, height=40)
        self.pc_frames["message"] = f

    def _pc_show(self, state, message=""):
        self.pc_state = state
        for k, f in self.pc_frames.items():
            if k != state:
                f.pack_forget()
        self.pc_frames[state].pack(fill="both", expand=True)
        if state == "form":
            self.form_err.pack_forget()
            if message:
                self.form_err.configure(text=message)
                self.form_err.pack(fill="x", pady=(0, self.look.px(10)), before=self.connect_btn)
            self.root.after(50, self.f_app.entry.focus_set)
        if state == "message":
            self.msg_text.configure(text=message)
            self.msg_btn.pack_forget()
            if not message.startswith("Loading"):
                self.msg_btn.pack(anchor="w")
                self.msg_dot.set("#ff9fb4")
            else:
                self.msg_dot.set(T["dim"])
        self._pc_import_btn()

    # ------------------------------------------------------------------ drop zone
    def _build_drop(self, body):
        L = self.look
        box = tk.Frame(body, bg=T["drop"])
        box.place(relx=0.5, rely=0.5, anchor="center")
        body.configure(height=L.px(300))
        self.drop_box = box
        icon = tk.Canvas(box, width=L.px(64), height=L.px(64), bg=T["drop"], highlightthickness=0)
        icon.create_oval(0, 0, L.px(64) - 1, L.px(64) - 1, fill=T["chip"], outline=T["chip"])
        k, o = L.px(30) / 24, (L.px(64) - L.px(30)) / 2
        pts = lambda *xy: [o + v * k for v in xy]          # noqa: E731  (lucide "file-up" icon, 24-unit grid)
        lw = max(2, L.px(2))
        icon.create_line(*pts(14, 2, 6, 2), fill=T["link"], width=lw, capstyle="round")
        icon.create_line(*pts(6, 2, 4, 4, 4, 20, 6, 22, 18, 22, 20, 20, 20, 8, 14, 2), fill=T["link"], width=lw,
                         joinstyle="round", smooth=False)
        icon.create_line(*pts(14, 2, 14, 8, 20, 8), fill=T["link"], width=lw, joinstyle="round")
        icon.create_line(*pts(12, 18, 12, 12), fill=T["link"], width=lw, capstyle="round")
        icon.create_line(*pts(9, 15, 12, 12, 15, 15), fill=T["link"], width=lw, capstyle="round", joinstyle="round")
        icon.pack(pady=(0, L.px(14)))
        self.drop_title = label(box, L, "Drop chord charts here" if self.dnd else "Choose chord charts", size=26,
                                weight="bold", anchor="center")
        self.drop_title.pack()
        self.drop_text = label(box, L, "Any number of PDFs. Each stage chart is saved next to its original, and "
                                       "the original is never changed.", size=15, color="muted", wrap=440,
                               justify="center", anchor="center")
        self.drop_text.pack(pady=(L.px(14), L.px(20)))
        btns = tk.Frame(box, bg=T["drop"])
        btns.pack()
        Pill(btns, L, "Choose PDFs…", self.choose_files, kind="primary", size=15, height=46).pack(side="left")
        self.import_btn = Pill(btns, L, "Import from Planning Center", self.import_from_pc, kind="outline",
                               size=15, height=46, weight="semibold")
        self.drop_btns = btns
        self._refresh_drop_text()
        for w in (body, box, icon, self.drop_title, self.drop_text):
            w.bind("<ButtonRelease-1>", lambda e: self.choose_files())
            w.configure(cursor="hand2")
        self.register_drop_target(self.drop_panel)
        for w in (body, box, icon, self.drop_title, self.drop_text, btns):
            self.register_drop_target(w)

    def _refresh_drop_text(self):
        f = self.out_dir()
        where = ("saved in " + os.path.basename(f.rstrip("\\/"))) if f else "saved next to its original"
        self.drop_text.configure(text=f"Any number of PDFs. Each stage chart is {where}, and the original is "
                                      "never changed.")

    def _pc_import_btn(self):
        if self.pc_state == "connected":
            self.import_btn.pack(side="left", padx=(self.look.px(10), 0))
        else:
            self.import_btn.pack_forget()

    # ------------------------------------------------------------------ last finished
    def _build_last(self, body):
        L = self.look
        label(body, L, "LAST FINISHED", size=12, color="muted", weight="bold").pack(fill="x")
        self.preview = ChartPreview(body, L, width=LEFT_W - 36 - 44)
        self.preview.pack(pady=(L.px(12), L.px(12)))
        btns = tk.Frame(body, bg=T["card"])
        btns.pack(fill="x", side="bottom")
        btns.columnconfigure(0, weight=1, uniform="b")
        btns.columnconfigure(1, weight=1, uniform="b")
        self.last_open = Pill(btns, L, "Open", lambda: self.last and self.platform.open_file(self.last.out),
                              kind="outline", size=13, height=40, radius=8, padx=8, weight="semibold", fill_x=True)
        self.last_show = Pill(btns, L, "Show in folder",
                              lambda: self.last and self.platform.show_in_folder(self.last.out), kind="outline",
                              size=13, height=40, radius=8, padx=8, weight="semibold", fill_x=True)
        self.last_open.grid(row=0, column=0, sticky="ew", padx=(0, L.px(4)))
        self.last_show.grid(row=0, column=1, sticky="ew", padx=(L.px(4), 0))
        self.last_open.set_enabled(False)
        self.last_show.set_enabled(False)

    # ------------------------------------------------------------------ this batch
    def _build_batch(self, body):
        L = self.look
        head = tk.Frame(body, bg=T["card"])
        head.pack(fill="x", padx=L.px(20), pady=(L.px(14), L.px(12)))
        label(head, L, "This batch", size=15, weight="bold").pack(side="left")
        self.count_lab = label(head, L, "", size=13, color="muted")
        self.count_lab.pack(side="left", padx=(L.px(10), 0))
        self.clear_btn = Pill(head, L, "Clear finished", self.clear_finished, kind="link", size=13, height=32,
                              padx=4, weight="semibold")
        self.clear_btn.pack(side="right")
        separator(body, L).pack(fill="x")
        self.batch = Scroller(body, L, T["card"])
        self.batch.pack(fill="both", expand=True)
        self.batch.cv.configure(height=L.px(300))
        self.empty_lab = label(self.batch.inner, L, "Charts you convert show up here.", size=13, color="dim")
        self.empty_lab.pack(fill="x", padx=L.px(20), pady=L.px(18))
        self.register_drop_target(self.batch.cv)
        self.update_count()

    def update_count(self):
        if not hasattr(self, "count_lab"):
            return
        n = len(self.rows)
        done = sum(1 for r in self.rows if r.finished)
        self.count_lab.configure(text=f"{done} of {n} done" if n else "")
        if n:
            self.empty_lab.pack_forget()
        else:
            self.empty_lab.pack(fill="x", padx=self.look.px(20), pady=self.look.px(18))
        self.clear_btn.set_enabled(done > 0)

    def clear_finished(self):
        keep = []
        for r in self.rows:
            if r.finished:
                r.destroy()
            else:
                keep.append(r)
        self.rows = keep
        self.rows_by_job = {k: v for k, v in self.rows_by_job.items() if v in keep}
        self.update_count()

    def add_row(self, name, detail, state="waiting"):
        r = Row(self, name, detail, state)
        self.rows.append(r)
        self.update_count()
        self.root.after(30, lambda: self.batch.cv.yview_moveto(1.0))
        return r

    # ================================================================== scrolling
    def bind_wheel(self, widget):
        pass                                   # one global handler, see _wheel_bindings

    def _wheel_bindings(self):
        def on_wheel(e):
            w = self.root.winfo_containing(e.x_root, e.y_root)
            if w is None:
                return
            if self.batch.owns(w) and self.batch._shown:
                self.batch.wheel(e)
            elif self.scroll._shown:
                self.scroll.wheel(e)
        self.root.bind_all("<MouseWheel>", on_wheel, add="+")
        self.root.bind_all("<Button-4>", on_wheel, add="+")
        self.root.bind_all("<Button-5>", on_wheel, add="+")

    # ================================================================== drag and drop
    def register_drop_target(self, widget):
        if not self.dnd:
            return
        try:
            widget.drop_target_register(self.dnd)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.dnd_bind("<<DropEnter>>", lambda e: self._hot(True))
            widget.dnd_bind("<<DropLeave>>", lambda e: self._hot(False))
        except Exception:
            self.log_error("drop target:\n" + traceback.format_exc())

    def _hot(self, on):
        self.drop_panel.set_colors(T["drop_hot"] if on else T["drop"], T["accent"] if on else T["drop_line"])
        for w in [self.drop_box] + list(self.drop_box.winfo_children()):
            try:
                w.configure(bg=T["drop_hot"] if on else T["drop"])
            except tk.TclError:
                pass
        return "copy"

    def _on_drop(self, event):
        self._hot(False)
        paths = [p for p in self.root.tk.splitlist(event.data) if p]
        self.submit(paths)
        return "copy"

    # ================================================================== converting files
    def out_dir(self):
        f = self.settings.get("save_folder", "")
        if self.settings.get("save_mode") == "folder" and f and os.path.isdir(f):
            return f
        return None

    def choose_files(self):
        start = self.settings.get("last_open_dir") or os.path.expanduser("~")
        paths = filedialog.askopenfilenames(parent=self.root, title="Choose chord chart PDFs",
                                            initialdir=start if os.path.isdir(start) else None,
                                            filetypes=[("PDF files", "*.pdf *.PDF"), ("All files", "*.*")])
        if paths:
            self.settings["last_open_dir"] = os.path.dirname(paths[0])
            self.settings.save()
            self.submit(list(paths))

    def submit(self, paths):
        """Queue PDFs (from a drop, the file picker, the Dock or Send to) for conversion."""
        todo = []
        for p in paths:
            name = os.path.basename(p.rstrip("\\/")) or p
            if os.path.isdir(p):
                pdfs = sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".pdf")
                              and "stage chart" not in f.lower())
                if not pdfs:
                    self.add_row(name, "That folder has no PDFs in it.", "bad")
                todo += [(os.path.basename(x), x) for x in pdfs]
            elif not p.lower().endswith(".pdf"):
                self.add_row(name, "Only PDF files can be converted.", "bad")
            else:
                todo.append((name, p))
        out_dir = self.out_dir()
        where = f"saved in {os.path.basename(out_dir.rstrip(chr(92) + '/'))}" if out_dir else "saved next to original"
        js = []
        for name, p in todo:
            job = jobs.Job(p, out_dir, name)
            job.where = where
            self.rows_by_job[job.id] = self.add_row(name, "Waiting…")
            js.append(job)
        self.queue.submit(js)

    def _job_started(self, job):
        r = self.rows_by_job.get(job.id)
        if r:
            r.set("busy", "Reading chords and sections…")

    def _job_done(self, res):
        job = res.job
        r = self.rows_by_job.get(job.id)
        if job.origin == "planning_center":
            res = self._file_set_chart(res)
        if res.ok:
            pages = f"{res.pages} page{'s' if res.pages != 1 else ''}"
            key = f"Key of {res.key}" if res.key else "No key found on the chart"
            state = "done"
            if job.origin == "planning_center":
                where = "in the plan’s key" if job.plan_key else "no key on the plan"
                if job.plan_key and res.key and not pco.same_key(res.key, job.plan_key):
                    state = "check"
                    where = f"plan says {job.plan_key}. Charts are never transposed"
                elif job.plan_key and not res.key:
                    state = "check"
                    where = f"plan says {job.plan_key}"
            else:
                where = getattr(job, "where", "saved next to original")
            if r:
                r.set(state, f"{key} · {pages} · {where}", out=res.out)
            self.last = res
            self.preview.show(res.song, res.key)
            self.last_open.set_enabled(True)
            self.last_show.set_enabled(True)
        elif r:
            r.set("bad", res.lines[0] if res.lines else "Couldn’t convert.")
        if job.set_id:
            self._set_progress(job.set_id, job, res)

    # ================================================================== Planning Center
    def _start_pc(self):
        creds = secrets_store.load() if not self.smoke else None
        if not creds:
            self._pc_show("intro")
            return
        self.client = pco.Client(*creds)
        self._load_pc()

    def _bg(self, work, done=None, fail=None):
        """Run work() on a thread; done(result) or fail(exc) run on the window's thread."""
        def run():
            try:
                res = work()
            except Exception as e:
                if not isinstance(e, pco.PCOError):
                    self.log_error("planning center:\n" + traceback.format_exc())
                if fail:
                    self.queue.post(fail, e)
                return
            if done:
                self.queue.post(done, res)
        threading.Thread(target=run, daemon=True).start()

    def _connect(self):
        app_id, secret = self.f_app.get(), self.f_secret.get()
        if not app_id or not secret:
            self._pc_show("form", "Paste both the Application ID and the Secret.")
            return
        self.connect_btn.set_text("Connecting…")
        self.connect_btn.set_enabled(False)
        client = pco.Client(app_id, secret)

        def ok(org):
            self.connect_btn.set_text("Connect")
            self.connect_btn.set_enabled(True)
            secrets_store.save(app_id, secret)
            self.f_secret.set("")
            self.client = client
            self.org = org
            self._load_pc()

        def bad(e):
            self.connect_btn.set_text("Connect")
            self.connect_btn.set_enabled(True)
            self._pc_show("form", str(e) if isinstance(e, pco.PCOError) else "Couldn’t connect. Try again.")
        self._bg(client.check, ok, bad)

    def disconnect(self):
        secrets_store.forget()
        self.client = None
        self.plan = self.next_plan = None
        self.month_plans.clear()
        self.songs_cache.clear()
        self.f_app.set("")
        self._pc_show("intro")

    def _chosen_types(self):
        want = set(self.settings.get("pc_service_types") or [])
        return [s for s in self.service_types if not want or s.id in want] or self.service_types

    def _load_pc(self):
        if not self.client:
            self._pc_show("intro")
            return
        self._pc_show("message", "Loading your services…")
        client = self.client
        y, m = self.month

        def work():
            org = self.org or client.check()
            types = client.service_types()
            want = set(self.settings.get("pc_service_types") or [])
            chosen = [s for s in types if not want or s.id in want] or types
            nxt = client.next_plan(chosen)
            if nxt:
                ym = (nxt.day.year, nxt.day.month)
            else:
                ym = (y, m)
            plans = client.plans_between(chosen, dt.date(ym[0], ym[1], 1), _month_end(ym))
            return org, types, nxt, ym, plans

        def ok(res):
            self.org, self.service_types, self.next_plan, ym, plans = res
            self.month = ym
            self.month_plans = {ym: _by_day(plans)}
            self.plan = self.next_plan
            self._pc_show("connected")
            self._show_plan()

        def bad(e):
            if isinstance(e, pco.AuthError):
                self.client = None
                self._pc_show("form", str(e))
            else:
                self._pc_show("message", str(e) if isinstance(e, pco.PCOError) else
                              "Something went wrong loading Planning Center. Try again.")
        self._bg(work, ok, bad)

    def reload_pc(self):
        self.month_plans.clear()
        self.songs_cache.clear()
        if self.client:
            self._load_pc()

    def _show_plan(self):
        p = self.plan
        today = dt.date.today()
        y, m = self.month
        plans = self.month_plans.get((y, m), {})
        self.cal.show(y, m, plans, p.day if p else None, today)
        if not p:
            self.plan_when.configure(text="Next up")
            self.plan_date.configure(text="No upcoming plans")
            self.plan_info.configure(text="Pick a date with a plan below." if plans else
                                     "Nothing scheduled this month.")
            self.convert_set_btn.set_enabled(False)
            self._pc_import_btn()
            self.import_btn.set_enabled(False)
            return
        self.convert_set_btn.set_enabled(True)
        self.import_btn.set_enabled(True)
        is_next = self.next_plan is not None and p.id == self.next_plan.id
        self.plan_when.configure(text="Next up" if is_next else ("Earlier plan" if p.day and p.day < today
                                                                 else "Selected"))
        self.plan_date.configure(text=_nice_day(p.day) if p.day else p.dates)
        songs = self.songs_cache.get(p.id)
        name = p.name
        if len(self._chosen_types()) > 1 and p.service_type.name not in name:
            name = f"{p.service_type.name}: {name}"
        if songs is None:
            self.plan_info.configure(text=f"{name}")
            self._bg(lambda: self.client.songs(p), lambda s, pid=p.id: self._songs_loaded(pid, s), lambda e: None)
        else:
            self.plan_info.configure(text=f"{name} · {len(songs)} song{'s' if len(songs) != 1 else ''}")

    def _songs_loaded(self, plan_id, songs):
        self.songs_cache[plan_id] = songs
        if self.plan and self.plan.id == plan_id:
            self._show_plan()

    def _month_step(self, delta):
        if not self.client:
            return
        y, m = self.month
        m += delta
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self.month = (y, m)
        if (y, m) in self.month_plans:
            self._show_plan()
            return
        self.month_plans[(y, m)] = {}
        self._show_plan()
        types = self._chosen_types()

        def ok(plans, ym=(y, m)):
            self.month_plans[ym] = _by_day(plans)
            if self.month == ym:
                self._show_plan()

        def bad(e, ym=(y, m)):
            self.month_plans.pop(ym, None)
        self._bg(lambda: self.client.plans_between(types, dt.date(y, m, 1), _month_end((y, m))), ok, bad)

    def _pick_day(self, day, event):
        plans = self.month_plans.get(self.month, {}).get(day, [])
        if len(plans) == 1:
            self.plan = plans[0]
            self._show_plan()
            return
        menu = tk.Menu(self.root, tearoff=0)
        for p in plans:
            menu.add_command(label=f"{p.service_type.name}: {p.name}",
                             command=lambda p=p: (setattr(self, "plan", p), self._show_plan()))
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------ converting a set
    def convert_set(self, only=None):
        """Download each song's chart (in the plan's key when there is one), convert them all, then put
        them together in one PDF for the set (if that setting is on)."""
        p = self.plan
        if not (self.client and p):
            return
        folder = pco.plan_folder(self.settings.pc_folder(), p)
        set_id = f"{p.id}-{dt.datetime.now().timestamp()}"
        st = {"plan": p, "folder": folder, "order": [], "results": {}, "rows": {}, "pending": 0,
              "combined": bool(self.settings.get("pc_combined", True)), "started": False}
        self.sets[set_id] = st
        title_row = self.add_row(f"{_nice_day(p.day) if p.day else p.dates} · {p.name}",
                                 "Getting the songs from Planning Center…", "download")
        st["title_row"] = title_row
        client = self.client

        def work():
            songs = self.songs_cache.get(p.id) or client.songs(p)
            self.songs_cache[p.id] = songs
            chosen = [s for s in songs if only is None or s.id in only]
            self.queue.post(self._set_songs, set_id, chosen)
            for s in chosen:
                try:
                    att = client.best_chart(s)
                    if not att:
                        self.queue.post(self._set_song_failed, set_id, s.id, "missing",
                                        "No chord chart PDF on this song in Planning Center.")
                        continue
                    stem = pco.safe_name(s.title) + (f" - {s.key_name}" if s.key_name else "")
                    dest = os.path.join(folder, "Originals", stem + ".pdf")
                    client.download(att, dest)
                    self.queue.post(self._set_song_ready, set_id, s, dest, att)
                except Exception as e:
                    if not isinstance(e, pco.PCOError):
                        self.log_error(f"set song {s.title}:\n" + traceback.format_exc())
                    msg = str(e) if isinstance(e, pco.PCOError) else "Couldn’t download the chart."
                    self.queue.post(self._set_song_failed, set_id, s.id, "bad", msg)
            self.queue.post(self._set_all_queued, set_id)

        def bad(e):
            title_row.set("bad", str(e) if isinstance(e, pco.PCOError) else "Couldn’t read the plan.")
        self._bg(work, None, bad)

    def _file_set_chart(self, res):
        job = res.job
        work = job.out_dir
        st = self.sets.get(job.set_id)
        try:
            if res.ok and st:
                dest = os.path.join(st["folder"], f"{job.number:02d} {os.path.basename(res.out)}")
                os.replace(res.out, dest)
                res.out = dest
        except OSError:
            self.log_error("filing set chart:\n" + traceback.format_exc())
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
            try:
                os.rmdir(os.path.dirname(work))
            except OSError:
                pass
        return res

    def _set_songs(self, set_id, songs):
        st = self.sets[set_id]
        st["title_row"].set("download", f"{len(songs)} song{'s' if len(songs) != 1 else ''} · downloading charts…")
        for s in songs:
            st["order"].append(s.id)
            st["titles"] = st.get("titles", {})
            st["titles"][s.id] = s.title
            st["rows"][s.id] = self.add_row(s.title, f"Plan key {s.key_name}" if s.key_name else "No key on the plan",
                                            "download")
            st["pending"] += 1
        if not songs:
            st["title_row"].set("missing", "This plan has no songs.")

    def _set_song_failed(self, set_id, song_id, state, msg):
        st = self.sets[set_id]
        r = st["rows"].get(song_id)
        if r:
            r.set(state, msg)
        st["results"][song_id] = None
        st["pending"] -= 1
        self._maybe_finish_set(set_id)

    def _set_song_ready(self, set_id, song, path, att):
        st = self.sets[set_id]
        # convert into a folder of its own, then file it as "01 Title - Stage Chart - D (Light).pdf" in
        # service order, so two songs can never overwrite each other
        work = os.path.join(st["folder"], ".converting", song.id)
        os.makedirs(work, exist_ok=True)
        job = jobs.Job(path, work, song.title, origin="planning_center", plan_key=song.key_name, set_id=set_id)
        job.song_id = song.id
        job.number = st["order"].index(song.id) + 1
        r = st["rows"][song.id]
        self.rows_by_job[job.id] = r
        r.set("waiting", f"Downloaded {att.filename}")
        self.queue.submit([job])

    def _set_all_queued(self, set_id):
        st = self.sets[set_id]
        st["started"] = True
        self._maybe_finish_set(set_id)

    def _set_progress(self, set_id, job, res):
        st = self.sets.get(set_id)
        if not st:
            return
        st["results"][job.song_id] = res if res.ok else None
        st["pending"] -= 1
        self._maybe_finish_set(set_id)

    def _maybe_finish_set(self, set_id):
        st = self.sets[set_id]
        if not st["started"] or st["pending"] > 0 or st.get("finished"):
            return
        st["finished"] = True
        good = [(sid, st["results"].get(sid)) for sid in st["order"]]
        good = [(sid, r) for sid, r in good if r is not None]
        n, total = len(good), len(st["order"])
        tr = st["title_row"]
        p = st["plan"]
        if not total:
            return
        if not good:
            tr.set("bad", "None of the songs could be converted.")
            return
        if not st["combined"]:
            tr.set("done", f"{n} of {total} charts made · in {os.path.basename(st['folder'])}",
                   out=good[-1][1].out)
            tr.out = st["folder"]
            return
        out = os.path.join(st["folder"], pco.safe_name(pco.plan_label(p)) + " - Whole Set.pdf")
        tr.set("busy", "Putting the set together in one PDF…")

        def work():
            import setpdf
            return setpdf.combine([r.out for _, r in good], out, [st["titles"][sid] for sid, _ in good])

        def ok(pages):
            missing = f" · {total - n} missing" if n < total else ""
            tr.set("done" if n == total else "check",
                   f"Whole set · {n} songs · {pages} pages{missing}", out=out)

        def bad(e):
            self.log_error("set pdf:\n" + "".join(traceback.format_exception(e)))
            tr.set("bad", "The charts are made, but the one-PDF set couldn’t be saved.")
        self._bg(work, ok, bad)

    def import_from_pc(self):
        """Pick which of the selected plan's songs to convert."""
        if not (self.client and self.plan):
            return
        p = self.plan
        songs = self.songs_cache.get(p.id)
        if songs is None:
            self._bg(lambda: self.client.songs(p), lambda s: (self.songs_cache.__setitem__(p.id, s),
                                                              self.import_from_pc()),
                     lambda e: self.add_row(p.name, str(e), "bad"))
            return
        SongPicker(self, p, songs)

    # ================================================================== settings
    def open_settings(self):
        if self.settings_win and self.settings_win.top.winfo_exists():
            self.settings_win.top.lift()
            return
        self.settings_win = SettingsWindow(self)

    def open_about(self):
        AboutWindow(self)

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    # ================================================================== loop
    def _pump(self):
        try:
            for p in (self.pc_panel, self.drop_panel, self.last_panel):
                p.refit()
            self.queue.drain()
        except Exception:
            self.log_error("window:\n" + traceback.format_exc())
        self.root.after(80, self._pump)

    @property
    def busy(self):
        return self.queue.busy > 0 or any(not r.finished for r in self.rows)

    def run(self):
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        self.root.mainloop()


PILL_BAD_FG = "#ff9fb4"


def _month_end(ym):
    y, m = ym
    return dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)


def _by_day(plans):
    out = {}
    for p in plans:
        out.setdefault(p.day, []).append(p)
    return out


def _nice_day(d):
    return f"{calendar.day_name[d.weekday()]}, {calendar.month_abbr[d.month]} {d.day}"


# ====================================================================================================
# Dialogs (dark, like the window)
# ====================================================================================================
class Dialog:
    def __init__(self, win, title, width=520):
        self.win, L = win, win.look
        self.top = tk.Toplevel(win.root, bg=T["bg"])
        self.top.title(title)
        self.top.transient(win.root)
        dark_title_bar(self.top)
        self.top.bind("<Escape>", lambda e: self.close())
        self.scroll = Scroller(self.top, L, T["bg"])
        self.scroll.pack(fill="both", expand=True)
        self.body = tk.Frame(self.scroll.inner, bg=T["bg"])
        self.body.pack(fill="both", expand=True, padx=L.px(24), pady=L.px(22))
        self.width = L.px(width)

    def place(self):
        self.top.update_idletasks()
        L = self.win.look
        h = min(self.body.winfo_reqheight() + L.px(48), self.top.winfo_screenheight() - L.px(120))
        r = self.win.root
        x = r.winfo_rootx() + (r.winfo_width() - self.width) // 2
        y = r.winfo_rooty() + max(0, (r.winfo_height() - h) // 4)
        self.top.geometry(f"{self.width}x{h}+{max(0, x)}+{max(0, y)}")
        self.top.bind("<MouseWheel>", self.scroll.wheel)
        self.top.bind("<Button-4>", self.scroll.wheel)
        self.top.bind("<Button-5>", self.scroll.wheel)

    def section(self, title):
        L = self.win.look
        p = Panel(self.body, L, T["card"], T["card_line"])
        p.pack(fill="x", pady=(0, L.px(16)))
        label(p.body, L, title.upper(), size=12, color="muted", weight="bold").pack(fill="x", pady=(0, L.px(10)))
        return p.body

    def close(self):
        self.top.destroy()


class SongPicker(Dialog):
    def __init__(self, win, plan, songs):
        super().__init__(win, "Import from Planning Center", width=520)
        L = win.look
        label(self.body, L, f"{_nice_day(plan.day) if plan.day else plan.dates} · {plan.name}", size=18,
              weight="bold").pack(fill="x")
        label(self.body, L, "Choose the songs to make stage charts for. Each chart is downloaded in the key the "
                            "song is scheduled in when Planning Center has one.", size=14, color="muted",
              wrap=460).pack(fill="x", pady=(L.px(6), L.px(14)))
        box = self.section(f"{len(songs)} song{'s' if len(songs) != 1 else ''}")
        self.toggles = []
        for s in songs:
            t = Toggle(box, L, f"{s.title}" + (f"   ·   {s.key_name}" if s.key_name else ""), True)
            t.pack(fill="x", pady=L.px(4))
            self.toggles.append((s, t))
        if not songs:
            label(box, L, "This plan has no songs.", size=14, color="dim").pack(fill="x")
        btns = tk.Frame(self.body, bg=T["bg"])
        btns.pack(fill="x")
        Pill(btns, L, "Make stage charts", self._go, kind="primary", size=14, height=44).pack(side="right")
        Pill(btns, L, "Cancel", self.close, kind="outline", size=14, height=44, weight="semibold").pack(
            side="right", padx=(0, L.px(10)))
        self.place()

    def _go(self):
        ids = {s.id for s, t in self.toggles if t.value}
        self.close()
        if ids:
            self.win.convert_set(only=ids)


class SettingsWindow(Dialog):
    def __init__(self, win):
        super().__init__(win, "Settings", width=560)
        L, s = win.look, win.settings
        self.s = s
        label(self.body, L, "Settings", size=20, weight="bold").pack(fill="x", pady=(0, L.px(16)))

        # ---- Planning Center
        box = self.section("Planning Center")
        row = tk.Frame(box, bg=T["card"])
        row.pack(fill="x")
        if win.client:
            Dot(row, L, T["ok_dot"]).pack(side="left", padx=(0, L.px(8)))
            label(row, L, f"Connected{' to ' + win.org if win.org else ''}", size=14).pack(side="left")
            Pill(row, L, "Disconnect", self._disconnect, kind="outline", size=13, height=36, padx=14,
                 weight="semibold").pack(side="right")
        else:
            Dot(row, L, T["dim"]).pack(side="left", padx=(0, L.px(8)))
            label(row, L, "Not connected", size=14).pack(side="left")
            Pill(row, L, "Connect…", self._connect, kind="light", size=13, height=36, padx=14).pack(side="right")
        if win.client and win.service_types:
            label(box, L, "Show plans from", size=13, color="sub", weight="semibold").pack(
                fill="x", pady=(L.px(14), L.px(6)))
            chosen = set(s.get("pc_service_types") or [])
            self.type_toggles = []
            for st in win.service_types:
                t = Toggle(box, L, st.name, not chosen or st.id in chosen, command=lambda v: self._types())
                t.pack(fill="x", pady=L.px(3))
                self.type_toggles.append((st, t))
        label(box, L, "Save sets in", size=13, color="sub", weight="semibold").pack(fill="x",
                                                                                  pady=(L.px(14), L.px(6)))
        row = tk.Frame(box, bg=T["card"])
        row.pack(fill="x")
        self.pc_folder_lab = label(row, L, s.pc_folder(), size=13, color="muted", wrap=340)
        self.pc_folder_lab.pack(side="left", fill="x", expand=True)
        Pill(row, L, "Change…", self._pick_pc_folder, kind="outline", size=13, height=36, padx=14,
             weight="semibold").pack(side="right")
        label(box, L, "Each plan gets its own folder, with the downloaded charts in “Originals”.", size=12,
              color="dim", wrap=440).pack(fill="x", pady=(L.px(4), 0))
        Toggle(box, L, "Also make one PDF for the whole set, in service order", s.get("pc_combined", True),
               command=lambda v: self._set("pc_combined", v)).pack(fill="x", pady=(L.px(12), 0))

        # ---- dropped PDFs
        box = self.section("Charts you drop or choose")
        self.beside = Toggle(box, L, "Save next to the original", s.get("save_mode") != "folder",
                             command=self._beside)
        self.beside.pack(fill="x")
        row = tk.Frame(box, bg=T["card"])
        row.pack(fill="x", pady=(L.px(10), 0))
        self.folder_lab = label(row, L, "", size=13, color="muted", wrap=340)
        self.folder_lab.pack(side="left", fill="x", expand=True)
        Pill(row, L, "Choose folder…", self._pick_folder, kind="outline", size=13, height=36, padx=14,
             weight="semibold").pack(side="right")
        self._show_folder()

        # ---- updates
        box = self.section("Updates")
        try:
            import updater
            from version import VERSION
            state = updater.load_state()
            Toggle(box, L, "Check for updates automatically", state.get("auto_check", True),
                   command=self._auto_update).pack(fill="x")
            row = tk.Frame(box, bg=T["card"])
            row.pack(fill="x", pady=(L.px(10), 0))
            label(row, L, f"Stage Chart {VERSION}", size=13, color="muted").pack(side="left")
            Pill(row, L, "Check now", self._check_updates, kind="outline", size=13, height=36, padx=14,
                 weight="semibold").pack(side="right")
        except Exception:
            label(box, L, "Updates aren’t available in this copy.", size=13, color="muted").pack(fill="x")

        win.platform.settings_extras(win, self)

        box = self.section("About")
        credit(box, L, win, size=13)
        label(box, L, "Light mode, two columns, 17 pt lyrics, in the original key, page count matched where "
                      "possible. Repeats shown once with ×2, bridges printed in order with their cues, slash "
                      "chords like D/F#. The original PDF is never changed.", size=13, color="muted",
              wrap=440).pack(fill="x")
        about = label(box, L, "About Stage Chart", size=13, color="link", weight="semibold", cursor="hand2")
        about.pack(fill="x", pady=(L.px(8), 0))
        about.bind("<Button-1>", lambda e: (self.close(), win.open_about()))
        if win.platform.log_path:
            lnk = label(box, L, "Open the log folder", size=13, color="link", weight="semibold", cursor="hand2")
            lnk.pack(fill="x", pady=(L.px(8), 0))
            lnk.bind("<Button-1>", lambda e: self._open_logs())

        Pill(self.body, L, "Done", self.close, kind="light", size=14, height=44, padx=28).pack(anchor="e")
        self.place()

    def _set(self, k, v):
        self.s[k] = v
        self.s.save()

    def _types(self):
        on = [st.id for st, t in self.type_toggles if t.value]
        if not on:                                   # never hide everything
            for st, t in self.type_toggles:
                t.set(True)
            on = []
        elif len(on) == len(self.type_toggles):
            on = []
        self._set("pc_service_types", on)
        self.win.reload_pc()

    def _pick_pc_folder(self):
        d = filedialog.askdirectory(parent=self.top, title="Save Planning Center sets in",
                                    initialdir=self.s.pc_folder() if os.path.isdir(self.s.pc_folder()) else None)
        if d:
            self._set("pc_folder", os.path.normpath(d))
            self.pc_folder_lab.configure(text=self.s.pc_folder())

    def _show_folder(self):
        f = self.s.get("save_folder", "")
        if self.s.get("save_mode") == "folder" and f:
            self.folder_lab.configure(text=f"Saving in {f}")
        else:
            self.folder_lab.configure(text=f"Or always save in one folder{': ' + f if f else ''}")
        self.win._refresh_drop_text()

    def _beside(self, v):
        if v:
            self._set("save_mode", "beside")
        elif self.s.get("save_folder") and os.path.isdir(self.s["save_folder"]):
            self._set("save_mode", "folder")
        elif not self._pick_folder():
            self.beside.set(True)
        self._show_folder()

    def _pick_folder(self):
        start = self.s.get("save_folder") or os.path.expanduser("~")
        d = filedialog.askdirectory(parent=self.top, title="Save stage charts in this folder",
                                    initialdir=start if os.path.isdir(start) else None)
        if not d:
            return False
        self._set("save_folder", os.path.normpath(d))
        self._set("save_mode", "folder")
        self.beside.set(False)
        self._show_folder()
        return True

    def _auto_update(self, v):
        import updater
        st = updater.load_state()
        st["auto_check"] = bool(v)
        updater.save_state(st)

    def _check_updates(self):
        u = getattr(self.win, "updates", None)
        if u:
            u.check_now()

    def _disconnect(self):
        self.win.disconnect()
        self.close()

    def _connect(self):
        self.close()
        self.win._pc_show("form")

    def _open_logs(self):
        d = os.path.dirname(self.win.platform.log_path)
        os.makedirs(d, exist_ok=True)
        self.win.platform.open_file(d)


MAKER = "Strange Harmony"
MAKER_URL = "https://strangeharmony.com"


def credit(parent, L, win, size=14, anchor="w"):
    """“Lovingly made by Strange Harmony”, with the name linking to strangeharmony.com."""
    row = tk.Frame(parent, bg=parent["bg"])
    row.pack(anchor=anchor, pady=(0, L.px(10)))
    label(row, L, "Lovingly made by ", size=size, color="sub").pack(side="left")
    lnk = label(row, L, MAKER, size=size, color="link", weight="semibold", cursor="hand2")
    lnk.configure(font=L.font(size, "semibold"))
    lnk.pack(side="left")
    lnk.bind("<Button-1>", lambda e: win._open_url(MAKER_URL))
    lnk.bind("<Enter>", lambda e: lnk.configure(fg=T["link_hot"]))
    lnk.bind("<Leave>", lambda e: lnk.configure(fg=T["link"]))
    try:                                         # underline it so it reads as a link
        f = tk.font.Font(lnk, font=lnk.cget("font"))
        f.configure(underline=True)
        lnk.configure(font=f)
        lnk._font = f
    except Exception:
        pass
    return row


class AboutWindow(Dialog):
    def __init__(self, win):
        super().__init__(win, "About Stage Chart", width=440)
        L = win.look
        try:
            from version import VERSION
        except Exception:
            VERSION = ""
        icon = tk.Canvas(self.body, width=L.px(88), height=L.px(88), bg=T["bg"], highlightthickness=0)
        u = L.px(88) / 100
        round_rect(icon, 2 * u, 2 * u, 98 * u, 98 * u, 22 * u, fill="#2a2380", outline="#2a2380")
        round_rect(icon, 22 * u, 14 * u, 78 * u, 86 * u, 4 * u, fill="#ffffff", outline="#ffffff")
        for kind, x, y, w, h in (("#111111", 28, 21, 30, 4), ("#7a2cf0", 28, 31, 10, 3), ("#5a5d70", 28, 36, 19, 2.5),
                                 ("#7a2cf0", 28, 43, 8, 3), ("#5a5d70", 28, 48, 18, 2.5), ("#7a2cf0", 28, 55, 11, 3),
                                 ("#5a5d70", 28, 60, 17, 2.5), ("#7a2cf0", 53, 31, 9, 3), ("#5a5d70", 53, 36, 19, 2.5),
                                 ("#7a2cf0", 53, 43, 11, 3), ("#5a5d70", 53, 48, 17, 2.5)):
            round_rect(icon, x * u, y * u, (x + w) * u, (y + h) * u, h * u / 2, fill=kind, outline=kind)
        icon.pack(pady=(L.px(4), L.px(12)))
        label(self.body, L, "Stage Chart", size=22, weight="bold", anchor="center").pack()
        label(self.body, L, f"Version {VERSION}", size=13, color="muted", anchor="center").pack(
            pady=(L.px(2), L.px(14)))
        credit(self.body, L, win, size=15, anchor="center")
        label(self.body, L, "Light mode, two columns, 17 pt lyrics, in the original key, page count matched where "
                            "possible. Repeats shown once with ×2, bridges printed in order with their cues, slash "
                            "chords like D/F#. The original PDF is never changed.", size=13, color="muted",
              wrap=380, justify="center", anchor="center").pack(pady=(L.px(4), L.px(10)))
        label(self.body, L, "Font: Carlito (SIL Open Font License).", size=12, color="dim", anchor="center").pack(
            pady=(0, L.px(16)))
        Pill(self.body, L, "OK", self.close, kind="light", size=14, height=40, padx=32).pack()
        self.place()


def start_updates(win):
    """The shared update checker (GitHub Releases), wired to the window."""
    win.updates = None
    try:
        import update_ui
        win.updates = update_ui.UpdateUI(win.root, say=lambda text, tag=None: None, log_path=win.platform.log_path,
                                         log_error=win.log_error, busy=lambda: win.busy, quit=win.root.destroy)
        win.updates.start()
    except Exception:
        win.log_error("updates unavailable:\n" + traceback.format_exc())
