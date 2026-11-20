"""The look of the Stage Chart window (layout B2, dark) and the small Tk widgets it is built from.

Plain Tk buttons can't be colored on a Mac, so buttons, panels with rounded corners, the calendar,
progress bars and the chart preview are drawn on canvases. Colors are from the approved B2 mockup.
"""
import sys
import tkinter as tk
from tkinter import font as tkfont

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

T = {
    "bg": "#0b0c18",            # window (near-black navy)
    "card": "#141629",
    "card_line": "#272b4a",
    "drop": "#11132a",
    "drop_line": "#3a3f66",
    "drop_hot": "#191c3a",
    "chip": "#1f2342",
    "btn_line": "#353a5e",
    "row_line": "#1d2038",
    "text": "#eef0ff",
    "sub": "#cfd2ee",
    "muted": "#a9adcc",
    "dim": "#9599bd",
    "link": "#b3b8e6",
    "link_hot": "#d6d9f5",
    "accent": "#8b7cf6",        # soft violet: primary button, selected date, progress bars only
    "accent_hot": "#9d90f8",
    "light": "#eef0ff",         # white pill buttons
    "light_hot": "#ffffff",
    "on_light": "#0b0c18",
    "ok_dot": "#3fb56a",
    "field": "#0b0c18",
    "page": "#ffffff",
    "ink": "#111111",
    "chord": "#9e0d14",         # stage charts print chords dark red (see stagechart.py)
}
PILLS = {
    "waiting": ("#1f2342", "#a9adcc", "Waiting"),
    "download": ("#1f2342", "#d6d9f5", "Downloading"),
    "busy": ("#1f2342", "#d6d9f5", "Converting"),
    "done": ("#173524", "#7fdc9c", "Done"),
    "check": ("#2d1d4f", "#d9c2ff", "Check key"),
    "bad": ("#45182a", "#ff9fb4", "Couldn’t convert"),
    "missing": ("#45182a", "#ff9fb4", "No chart"),
}


class Look:
    """Fonts and a pixel scale, so the window looks the same on a 100% and a 150% Windows display."""

    def __init__(self, root):
        self.root = root
        if IS_MAC:
            self.k = 1.0
        else:
            try:
                self.k = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
            except Exception:
                self.k = 1.0
        fams = set(tkfont.families(root))
        if IS_WIN:
            fam = "Segoe UI Variable Text" if "Segoe UI Variable Text" in fams else "Segoe UI"
            semi = "Segoe UI Semibold" if "Segoe UI Semibold" in fams else None
        elif IS_MAC:
            fam = next((f for f in ("SF Pro Text", "SF Pro", "Helvetica Neue") if f in fams), "Helvetica")
            semi = None
        else:
            fam = next((f for f in ("Inter", "Cantarell", "DejaVu Sans") if f in fams), "TkDefaultFont")
            semi = None
        self.family = fam
        self._fonts = {}
        self._semi = semi

    def px(self, n):
        return int(round(n * self.k))

    def font(self, size, weight="normal"):
        key = (size, weight)
        if key not in self._fonts:
            fam = self.family
            w = weight
            if weight == "semibold":
                if self._semi:
                    fam, w = self._semi, "normal"
                else:
                    w = "bold"
            # negative size = pixels, so text keeps its size relative to the drawn shapes
            self._fonts[key] = tkfont.Font(self.root, family=fam, size=-self.px(size), weight=w)
        return self._fonts[key]


def round_rect(cv, x0, y0, x1, y1, r, **kw):
    """A rounded rectangle as one smooth polygon."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, splinesteps=12, **kw)


class Panel(tk.Canvas):
    """A rounded card. Put children in .body. Stretches to whatever the grid gives it."""

    def __init__(self, parent, look, fill, line, radius=16, pad=18, dash=None, width_px=None, line_w=1):
        bg = parent["bg"] if "bg" in parent.keys() else T["bg"]
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.look, self.fill, self.line, self.dash, self.line_w = look, fill, line, dash, line_w
        self.r, self.pad = look.px(radius), look.px(pad)
        self.body = tk.Frame(self, bg=fill)
        self._win = self.create_window(self.pad, self.pad, anchor="nw", window=self.body)
        self._shape = None
        if width_px:
            self.configure(width=look.px(width_px))
        self.bind("<Configure>", self._redraw)
        self.body.bind("<Configure>", self._body_size)

    def set_colors(self, fill=None, line=None):
        self.fill = fill or self.fill
        self.line = line or self.line
        self.body.configure(bg=self.fill)
        self._redraw()

    def _body_size(self, e=None):
        want = self.body.winfo_reqheight() + 2 * self.pad
        if int(self.cget("height")) != want:
            self.configure(height=want)
            self._redraw()

    def refit(self):
        """Grow or shrink with the content (the window calls this regularly; Tk doesn't tell a canvas)."""
        self._body_size()

    def _redraw(self, e=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        if self._shape:
            self.delete(self._shape)
        lw = self.look.px(self.line_w) if self.line_w > 1 else 1
        o = lw / 2 + 0.5
        kw = {"fill": self.fill, "outline": self.line, "width": lw}
        if self.dash:
            kw["dash"] = self.dash
        self._shape = round_rect(self, o, o, w - o, h - o, self.r, **kw)
        self.tag_lower(self._shape)
        self.itemconfigure(self._win, width=max(1, w - 2 * self.pad),
                           height=max(self.body.winfo_reqheight(), h - 2 * self.pad))


class Pill(tk.Canvas):
    """A button drawn as a pill (or a rounded square). kind: primary, light, outline, ghost, link."""

    STYLES = {
        "primary": ("accent", "accent_hot", None, "on_light"),
        "light": ("light", "light_hot", None, "on_light"),
        "outline": (None, "chip", "btn_line", "text"),
        "chrome": ("card", "chip", "btn_line", "text"),
        "ghost": (None, "chip", None, "link"),
        "link": (None, None, None, "link"),
    }

    def __init__(self, parent, look, text, command=None, kind="outline", size=14, height=44, padx=22,
                 radius=None, weight="bold", width=None, fill_x=False):
        bg = parent["bg"]
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, takefocus=1, cursor="hand2")
        self.look, self.kind, self.command, self.text = look, kind, command, text
        self.f = look.font(size, weight)
        self.h = look.px(height)
        self.radius = None if radius is None else look.px(radius)
        self.padx = look.px(padx)
        self.fixed_w = look.px(width) if width else None
        self.fill_x = fill_x
        self.hover = self.focus = False
        self.enabled = True
        self.configure(height=self.h, width=self.fixed_w or (self.f.measure(text) + 2 * self.padx))
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False))
        self.bind("<FocusIn>", lambda e: self._set(focus=True))
        self.bind("<FocusOut>", lambda e: self._set(focus=False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def set_text(self, text):
        self.text = text
        if not self.fixed_w and not self.fill_x:
            self.configure(width=self.f.measure(text) + 2 * self.padx)
        self.draw()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow", takefocus=1 if on else 0)
        self.draw()

    def _click(self, e=None):
        if not self.enabled or not self.command:
            return
        if e is not None and e.type == tk.EventType.ButtonRelease:
            if not (0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()):
                return
        self.command()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            w = int(self.cget("width"))
            h = int(self.cget("height"))
        fill, hot, line, fg = self.STYLES[self.kind]
        bgc = T[hot] if (self.hover and self.enabled and hot) else (T[fill] if fill else self["bg"])
        r = h / 2 if self.radius is None else self.radius
        if self.kind != "link":
            round_rect(self, 0.5, 0.5, w - 1, h - 1, r, fill=bgc, outline=T[line] if line else bgc)
        if self.focus and self.enabled:
            round_rect(self, 1.5, 1.5, w - 2, h - 2, r, fill="", outline=T["accent"], width=2)
        col = T[fg]
        if self.kind == "link" and self.hover:
            col = T["link_hot"]
        if not self.enabled:
            col = T["dim"] if self.kind not in ("light", "primary") else "#6c6f8f"
        self.create_text(w / 2, h / 2, text=self.text, font=self.f, fill=col)


class Toggle(tk.Frame):
    """A checkbox with a label, drawn so it matches on both platforms."""

    def __init__(self, parent, look, text, value=False, command=None, size=14):
        super().__init__(parent, bg=parent["bg"])
        self.look, self.value, self.command = look, bool(value), command
        s = look.px(20)
        self.box = tk.Canvas(self, width=s, height=s, bg=parent["bg"], highlightthickness=0, takefocus=1,
                             cursor="hand2")
        self.box.pack(side="left")
        self.lab = tk.Label(self, text=text, bg=parent["bg"], fg=T["sub"], font=look.font(size), cursor="hand2",
                            justify="left", anchor="w")
        self.lab.pack(side="left", padx=(look.px(10), 0), fill="x")
        for w in (self.box, self.lab):
            w.bind("<ButtonRelease-1>", lambda e: self.flip())
        self.box.bind("<space>", lambda e: self.flip())
        self.box.bind("<FocusIn>", lambda e: self.draw(True))
        self.box.bind("<FocusOut>", lambda e: self.draw(False))
        self.draw()

    def flip(self):
        self.value = not self.value
        self.draw()
        if self.command:
            self.command(self.value)

    def set(self, v):
        self.value = bool(v)
        self.draw()

    def draw(self, focus=False):
        c, s = self.box, int(self.box.cget("width"))
        c.delete("all")
        if self.value:
            round_rect(c, 1, 1, s - 1, s - 1, self.look.px(5), fill=T["accent"], outline=T["accent"])
            k = s / 20
            c.create_line(5 * k, 10.5 * k, 8.5 * k, 14 * k, 15 * k, 6.5 * k, fill=T["on_light"],
                          width=max(2, int(2.2 * k)), capstyle="round", joinstyle="round")
        else:
            round_rect(c, 1, 1, s - 1, s - 1, self.look.px(5), fill=T["field"], outline=T["btn_line"])
        if focus:
            round_rect(c, 0, 0, s, s, self.look.px(6), fill="", outline=T["link"], width=1)


class Dot(tk.Canvas):
    def __init__(self, parent, look, color, size=8):
        s = look.px(size)
        super().__init__(parent, width=s, height=s, bg=parent["bg"], highlightthickness=0)
        self.oval = self.create_oval(0, 0, s - 1, s - 1, fill=color, outline=color)

    def set(self, color):
        self.itemconfigure(self.oval, fill=color, outline=color)


class Bar(tk.Canvas):
    """Thin progress bar. value None = moving (we can't know how far the engine is)."""

    def __init__(self, parent, look, width=320):
        super().__init__(parent, height=look.px(5), width=look.px(width), bg=parent["bg"], highlightthickness=0)
        self.look = look
        self.pos = 0.0
        self.running = False

    def start(self):
        if not self.running:
            self.running = True
            self._tick()

    def stop(self):
        self.running = False

    def _tick(self):
        if not self.running or not self.winfo_exists():
            return
        self.pos = (self.pos + 0.025) % 1.4
        w, h = self.winfo_width(), self.winfo_height()
        self.delete("all")
        round_rect(self, 0, 0, w, h, h / 2, fill=T["card_line"], outline=T["card_line"])
        seg = w * 0.35
        x0 = max(0, (self.pos - 0.35) * w)
        x1 = min(w, x0 + seg if self.pos > 0.35 else self.pos * w)
        if x1 - x0 > 2:
            round_rect(self, x0, 0, x1, h, h / 2, fill=T["accent"], outline=T["accent"])
        self.after(30, self._tick)


class Badge(tk.Canvas):
    """Status pill: Done, Converting, Couldn't convert…"""

    def __init__(self, parent, look):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, height=look.px(26), width=10)
        self.look = look
        self.f = look.font(12, "bold")

    def set(self, kind):
        bg, fg, text = PILLS[kind]
        w = self.f.measure(text) + self.look.px(20)
        h = self.look.px(26)
        self.configure(width=w)
        self.delete("all")
        round_rect(self, 0, 0, w, h, h / 2, fill=bg, outline=bg)
        self.create_text(w / 2, h / 2, text=text, fill=fg, font=self.f)


class Field(tk.Frame):
    """A labelled text box."""

    def __init__(self, parent, look, label, show=None, placeholder=""):
        super().__init__(parent, bg=parent["bg"])
        tk.Label(self, text=label, bg=parent["bg"], fg=T["sub"], font=look.font(13, "semibold"),
                 anchor="w").pack(fill="x", pady=(0, look.px(6)))
        box = tk.Frame(self, bg=T["field"], highlightthickness=1, highlightbackground=T["btn_line"],
                       highlightcolor=T["accent"])
        box.pack(fill="x")
        self.var = tk.StringVar()
        self.entry = tk.Entry(box, textvariable=self.var, show=show or "", bg=T["field"], fg=T["text"],
                              insertbackground=T["text"], relief="flat", bd=0, font=look.font(14),
                              highlightthickness=0, disabledbackground=T["field"])
        self.entry.pack(fill="x", padx=look.px(12), pady=look.px(10))
        self.placeholder = placeholder
        if placeholder:
            self._ph = tk.Label(box, text=placeholder, bg=T["field"], fg="#6c6f8f", font=look.font(14),
                                anchor="w", cursor="xterm")
            self._ph.bind("<Button-1>", lambda e: self.entry.focus_set())
            self.var.trace_add("write", lambda *a: self._sync())
            self.entry.bind("<FocusIn>", lambda e: self._sync())
            self.entry.bind("<FocusOut>", lambda e: self._sync())
            self.after(10, self._sync)
        # paste works with the platform shortcut even when the keyboard layout is unusual
        self.entry.bind("<<Paste>>", self._paste)

    def _paste(self, e):
        try:
            text = self.entry.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            self.entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        self.entry.insert("insert", text.strip())
        return "break"

    def _sync(self):
        if not self.placeholder:
            return
        if self.var.get():
            self._ph.place_forget()
        else:
            self._ph.place(in_=self.entry, x=0, rely=0.5, anchor="w", relwidth=1)

    def get(self):
        return self.var.get().strip()

    def set(self, v):
        self.var.set(v)


def label(parent, look, text, size=14, color="text", weight="normal", wrap=0, **kw):
    lab = tk.Label(parent, text=text, bg=parent["bg"], fg=T[color], font=look.font(size, weight),
                   justify=kw.pop("justify", "left"), anchor=kw.pop("anchor", "w"),
                   wraplength=look.px(wrap) if wrap else 0, **kw)
    return lab


def separator(parent, look, color="card_line"):
    return tk.Frame(parent, bg=T[color], height=1)


class Scroller(tk.Frame):
    """A vertically scrolling area. Put children in .inner. The scroll bar shows only when needed."""

    def __init__(self, parent, look, bg):
        super().__init__(parent, bg=bg)
        self.look = look
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.cv, bg=bg)
        self.win = self.cv.create_window(0, 0, anchor="nw", window=self.inner)
        self.bar = tk.Canvas(self, width=look.px(8), bg=bg, highlightthickness=0)
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self._update())
        self.cv.bind("<Configure>", lambda e: self._update())
        self.bar.bind("<Button-1>", self._drag)
        self.bar.bind("<B1-Motion>", self._drag)
        self._shown = False

    def _update(self):
        cw, ch = self.cv.winfo_width(), self.cv.winfo_height()
        ih = self.inner.winfo_reqheight()
        self.cv.itemconfigure(self.win, width=cw)
        self.cv.configure(scrollregion=(0, 0, cw, max(ih, ch)))
        need = ih > ch + 1
        if need != self._shown:
            self._shown = need
            if need:
                self.bar.pack(side="right", fill="y", padx=(0, self.look.px(4)), pady=self.look.px(6))
            else:
                self.bar.pack_forget()
                self.cv.yview_moveto(0)
        self._draw_bar()

    def _draw_bar(self):
        self.bar.delete("all")
        if not self._shown:
            return
        a, b = self.cv.yview()
        h, w = self.bar.winfo_height(), int(self.bar.cget("width"))
        round_rect(self.bar, 1, a * h, w - 1, max(a * h + 20, b * h), w / 2, fill=T["btn_line"],
                   outline=T["btn_line"])

    def _drag(self, e):
        h = max(1, self.bar.winfo_height())
        a, b = self.cv.yview()
        self.cv.yview_moveto(max(0, e.y / h - (b - a) / 2))
        self._draw_bar()

    def wheel(self, e):
        if not self._shown:
            return
        if IS_MAC:
            step = -e.delta
        elif getattr(e, "num", 0) in (4, 5):
            step = -1 if e.num == 4 else 1
        else:
            step = -e.delta / 120
        self.cv.yview_scroll(int(step) or (1 if step > 0 else -1), "units")
        self._draw_bar()

    def owns(self, widget):
        w = widget
        while w is not None:
            if w is self:
                return True
            w = getattr(w, "master", None)
        return False


# --------------------------------------------------------------------------------------------
# The month calendar in the Planning Center card
# --------------------------------------------------------------------------------------------
class Calendar(tk.Frame):
    def __init__(self, parent, look, on_month, on_pick):
        super().__init__(parent, bg=parent["bg"])
        self.look, self.on_month, self.on_pick = look, on_month, on_pick
        self.year = self.month = 0
        self.plans = {}            # date -> [Plan]
        self.selected = None
        self.today = None
        top = tk.Frame(self, bg=parent["bg"])
        top.pack(fill="x", pady=(0, look.px(4)))
        self.prev = Pill(top, look, "‹", lambda: on_month(-1), kind="ghost", size=18, height=32, width=32,
                         radius=8, weight="normal")
        self.prev.pack(side="left")
        self.next = Pill(top, look, "›", lambda: on_month(1), kind="ghost", size=18, height=32, width=32,
                         radius=8, weight="normal")
        self.next.pack(side="right")
        self.title = label(top, look, "", size=13, weight="bold", anchor="center")
        self.title.pack(side="left", fill="x", expand=True)
        self.cv = tk.Canvas(self, bg=parent["bg"], highlightthickness=0, height=look.px(16 + 6 * 30))
        self.cv.pack(fill="x")
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<ButtonRelease-1>", self._click)
        self.cv.bind("<Motion>", self._motion)
        self.cells = []

    def show(self, year, month, plans, selected, today):
        self.year, self.month, self.plans, self.selected, self.today = year, month, plans, selected, today
        import calendar
        self.title.configure(text=f"{calendar.month_name[month]} {year}")
        self.draw()

    def draw(self):
        import calendar
        import datetime as dt
        cv, L = self.cv, self.look
        cv.delete("all")
        w = cv.winfo_width()
        if w < 20 or not self.year:
            return
        colw = w / 7
        f_dow = L.font(11, "semibold")
        for i, d in enumerate("SMTWTFS"):
            cv.create_text(colw * i + colw / 2, L.px(7), text=d, fill=T["dim"], font=f_dow)
        cal = calendar.Calendar(firstweekday=6)            # weeks start on Sunday, like the mockup
        weeks = cal.monthdayscalendar(self.year, self.month)
        top = L.px(16)
        rowh = L.px(30)
        cellh = L.px(28)
        self.cells = []
        for r, week in enumerate(weeks):
            for c, n in enumerate(week):
                if not n:
                    continue
                day = dt.date(self.year, self.month, n)
                x0, y0 = colw * c + 1, top + r * rowh + 1
                x1, y1 = colw * (c + 1) - 1, y0 + cellh
                has = day in self.plans
                sel = self.selected is not None and day == self.selected
                bg = T["accent"] if sel else (T["chip"] if has else None)
                fg = T["on_light"] if sel else ("#d6d9f5" if has else ("#ffffff" if day == self.today else T["sub"]))
                bold = has or sel or day == self.today
                if bg:
                    round_rect(cv, x0, y0, x1, y1, L.px(7), fill=bg, outline=bg)
                if day == self.today and not sel:
                    cv.create_line(x0 + colw * 0.35, y1 - L.px(4), x1 - colw * 0.35, y1 - L.px(4),
                                   fill=T["link"], width=max(1, L.px(1.5)))
                cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=str(n), fill=fg,
                               font=L.font(12, "bold" if bold else "normal"))
                self.cells.append((x0, y0, x1, y1, day))
        self.cv.configure(height=top + len(weeks) * rowh)

    def _hit(self, e):
        for x0, y0, x1, y1, day in self.cells:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return day
        return None

    def _motion(self, e):
        d = self._hit(e)
        self.cv.configure(cursor="hand2" if d in self.plans else "")

    def _click(self, e):
        d = self._hit(e)
        if d in self.plans:
            self.on_pick(d, e)


# --------------------------------------------------------------------------------------------
# "Last finished" page preview, drawn from the parsed song (no PDF renderer needed)
# --------------------------------------------------------------------------------------------
class ChartPreview(tk.Canvas):
    RATIO = 11 / 8.5

    def __init__(self, parent, look, width=210):
        self.look = look
        self.pw = look.px(width)
        self.ph = int(self.pw * self.RATIO)
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, width=self.pw + 8, height=self.ph + 8)
        self.song = None
        self.key = ""
        self.draw()

    def show(self, song, key=""):
        self.song, self.key = song, key
        self.draw()

    def draw(self):
        import re
        L = self.look
        self.delete("all")
        pw, ph = self.pw, self.ph
        ox, oy = 4, 2
        self.create_rectangle(ox + 2, oy + 4, ox + pw + 2, oy + ph + 4, fill="#05060c", outline="")
        if not self.song:
            self.create_rectangle(ox, oy, ox + pw, oy + ph, fill=T["drop"], outline=T["btn_line"], dash=(3, 3))
            self.create_text(ox + pw / 2, oy + ph / 2, text="Your newest stage chart\nshows here.",
                             fill=T["dim"], font=L.font(12), justify="center")
            return
        self.create_rectangle(ox, oy, ox + pw, oy + ph, fill=T["page"], outline="")
        s = self.song
        m = pw * 0.055
        f_t = L.font(max(8, int(pw / 19)), "bold")
        f_k = L.font(max(6, int(pw / 32)), "bold")
        f_h = L.font(max(5, int(pw / 38)), "bold")
        f_l = L.font(max(5, int(pw / 40)))
        title = s.title or "Untitled"
        while f_t.measure(title) > pw * 0.68 and len(title) > 4:
            title = title[:-2].rstrip() + "…" if not title.endswith("…") else title[:-2] + "…"
        y = oy + m
        self.create_text(ox + m, y, text=title, anchor="nw", font=f_t, fill=T["ink"])
        key = self.key or s.key
        if key:
            self.create_text(ox + pw - m, y + f_t.metrics("linespace") - f_k.metrics("linespace"),
                             text=f"Key of {key}", anchor="nw" if False else "ne", font=f_k, fill=T["ink"])
        y += f_t.metrics("linespace") + 2
        self.create_line(ox + m, y, ox + pw - m, y, fill=T["ink"], width=1.5)
        y += 5
        colw = (pw - 2 * m - pw * 0.04) / 2
        cols = [ox + m, ox + m + colw + pw * 0.04]
        lh = f_l.metrics("linespace")
        top, col, bottom = y, 0, oy + ph - m
        for sec in s.sections:
            head = sec.label.upper() + (f"  ×{sec.times}" if sec.times > 1 else "")
            need = lh * 2
            if y + need > bottom:
                if col == 1:
                    break
                col, y = 1, top
            self.create_text(cols[col], y, text=head, anchor="nw", font=f_h, fill=T["ink"])
            y += f_h.metrics("linespace")
            for line in sec.lines:
                if not isinstance(line, str):
                    continue
                chords = " ".join(re.findall(r"\[([^\]]*)\]", line))
                words = re.sub(r"\[[^\]]*\]", "", line).strip()
                rows = ([("c", chords)] if chords else []) + ([("l", words)] if words else [])
                if y + lh * len(rows) > bottom:
                    if col == 1:
                        return
                    col, y = 1, top
                for kind, text in rows:
                    fnt = f_h if kind == "c" else f_l
                    while fnt.measure(text) > colw and len(text) > 3:
                        text = text[:-2]
                    self.create_text(cols[col], y, text=text, anchor="nw", font=fnt,
                                     fill=T["chord"] if kind == "c" else T["ink"])
                    y += lh
            y += lh * 0.6


def dark_title_bar(root):
    """Ask the system for a dark window frame to match (Windows 10 1809+ and macOS 10.14+)."""
    try:
        if IS_MAC:
            root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", root, "darkaqua")
        elif IS_WIN:
            import ctypes
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):            # DWMWA_USE_IMMERSIVE_DARK_MODE (new, then pre-20H1)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                                              ctypes.sizeof(val)) == 0:
                    break
    except Exception:
        pass
