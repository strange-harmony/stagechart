"""The update window shared by the Mac and Windows apps (Tk). The work itself is in updater.py.

    ui = UpdateUI(root, say=..., log_path=LOG, log_error=log_error, busy=lambda: False, quit=root.destroy)
    ui.start()        # tidy up after an earlier update, then check quietly if a day has passed
    ui.check_now()    # menu item "Check for Updates…"
"""
import queue
import threading
import time
import traceback
import webbrowser

import updater
from version import VERSION


class UpdateUI:
    def __init__(self, root, say, log_path, log_error, busy=lambda: False, quit=None):
        self.root = root
        self.say = say
        self.log_path = log_path
        self.log_error = log_error
        self.busy = busy
        self.quit = quit or root.destroy
        self.events = queue.Queue()
        self.checking = False
        self.dialog = None
        self.root.after(200, self._pump)

    # ------------------------------------------------------------------ public
    def start(self):
        threading.Thread(target=self._cleanup, daemon=True).start()
        state = updater.load_state()
        if updater.platform_key() and updater.due_for_check(state):
            self.root.after(4000, lambda: self._check(manual=False))

    def check_now(self):
        self._check(manual=True)

    # ------------------------------------------------------------------ internals
    def _pump(self):
        try:
            while True:
                fn, args = self.events.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    self.log_error("update window:\n" + traceback.format_exc())
        except queue.Empty:
            pass
        try:
            self.root.after(150, self._pump)
        except Exception:
            pass

    def _later(self, fn, *args):
        self.events.put((fn, args))

    def _cleanup(self):
        time.sleep(5)                     # let a just-finished swap helper exit first
        try:
            updater.cleanup()
        except Exception:
            pass

    def _check(self, manual):
        if self.checking or self.dialog is not None:
            if manual and self.dialog is not None:
                self.dialog.lift()
            return
        self.checking = True
        if manual:
            self.say("Checking for updates …")

        def work():
            try:
                rel = updater.check()
                err = None
            except Exception as e:
                rel, err = None, e
                if not isinstance(e, updater.UpdateError):
                    self.log_error("update check:\n" + traceback.format_exc())
            state = updater.load_state()
            if err is None:
                state["last_check"] = time.time()
                updater.save_state(state)
            self._later(self._checked, manual, rel, err, state)

        threading.Thread(target=work, daemon=True).start()

    def _checked(self, manual, rel, err, state):
        from tkinter import messagebox
        self.checking = False
        if err is not None:
            if manual:
                self.say("✗ " + str(err), "bad")
                messagebox.showwarning("Stage Chart", str(err), parent=self.root)
            return
        if rel is None:
            if manual:
                self.say(f"Stage Chart {VERSION} is the newest version.", "ok")
                messagebox.showinfo("Stage Chart", f"You have the newest version of Stage Chart ({VERSION}).",
                                    parent=self.root)
            return
        if not manual and state.get("skip_version") == rel["version"]:
            return
        self.say(f"Stage Chart {rel['version']} is available (you have {VERSION}).")
        self._show(rel, manual)

    def _show(self, rel, manual):
        import tkinter as tk
        ok, why = updater.can_install()
        d = tk.Toplevel(self.root)
        self.dialog = d
        d.title("Update Stage Chart")
        d.transient(self.root)
        d.resizable(False, False)
        d.protocol("WM_DELETE_WINDOW", self._close)
        pad = {"padx": 18}
        from tkinter import font as tkfont
        title = tkfont.nametofont("TkDefaultFont").copy()
        title.configure(weight="bold", size=abs(int(title.cget("size"))) + 3)
        self._title_font = title
        tk.Label(d, text=f"Stage Chart {rel['version']} is available", font=title,
                 anchor="w", justify="left").pack(fill="x", pady=(16, 2), **pad)
        tk.Label(d, text=f"You have version {VERSION}.", anchor="w", justify="left").pack(fill="x", **pad)
        if rel["notes"]:
            tk.Label(d, text="What's new:", anchor="w").pack(fill="x", pady=(10, 2), **pad)
            notes = tk.Text(d, width=60, height=min(12, max(3, rel["notes"].count("\n") + 2)), wrap="word",
                            relief="flat", highlightthickness=1, highlightbackground="#d2d2d7", padx=8, pady=6)
            notes.insert("1.0", rel["notes"])
            notes.configure(state="disabled")
            notes.pack(fill="x", **pad)
        msg = ("Stage Chart will close, update itself and open again. It takes about a minute."
               if ok else why + "\n\nYou can download the new version from GitHub instead.")
        self.status = tk.Label(d, text=msg, anchor="w", justify="left", wraplength=440)
        self.status.pack(fill="x", pady=(12, 4), **pad)

        btns = tk.Frame(d)
        btns.pack(fill="x", pady=(6, 16), **pad)
        self.buttons = []
        if ok:
            b = tk.Button(btns, text="Install and Restart", default="active",
                          command=lambda: self._install(rel))
        else:
            b = tk.Button(btns, text="Open Download Page", default="active",
                          command=lambda: (webbrowser.open(rel["page"]), self._close()))
        b.pack(side="right")
        self.buttons.append(b)
        b2 = tk.Button(btns, text="Later", command=self._close)
        b2.pack(side="right", padx=6)
        self.buttons.append(b2)
        if not manual:
            b3 = tk.Button(btns, text="Skip This Version", command=lambda: self._skip(rel))
            b3.pack(side="left")
            self.buttons.append(b3)
        d.bind("<Escape>", lambda e: self._close())
        d.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - d.winfo_reqwidth()) // 2)
        y = self.root.winfo_rooty() + 40
        d.geometry(f"+{x}+{y}")
        d.lift()
        d.focus_force()

    def _close(self):
        if self.dialog is not None and getattr(self, "installing", False):
            return
        if self.dialog is not None:
            self.dialog.destroy()
        self.dialog = None

    def _skip(self, rel):
        state = updater.load_state()
        state["skip_version"] = rel["version"]
        updater.save_state(state)
        self.say(f"Skipping Stage Chart {rel['version']}. Use Check for Updates to install it later.")
        self._close()

    def _install(self, rel):
        from tkinter import messagebox
        if self.busy():
            messagebox.showinfo("Stage Chart", "Stage Chart is still converting charts. Try again when it's done.",
                                parent=self.dialog)
            return
        self.installing = True
        for b in self.buttons:
            b.configure(state="disabled")
        self.status.configure(text="Downloading …")

        def progress(done, total):
            if total:
                self._later(self.status.configure, {"text": f"Downloading … {done * 100 // total}%"})

        def work():
            try:
                zpath = updater.download(rel, updater.work_dir(), progress)
                self._later(self.status.configure, {"text": "Unpacking …"})
                new_app = updater.prepare(zpath, rel["version"])
                self._later(self._swap, rel, new_app)
            except Exception as e:
                if not isinstance(e, updater.UpdateError):
                    self.log_error("update install:\n" + traceback.format_exc())
                self._later(self._failed, e)

        threading.Thread(target=work, daemon=True).start()

    def _swap(self, rel, new_app):
        try:
            updater.launch_swap(new_app, self.log_path)
        except Exception as e:
            self.log_error("update swap:\n" + traceback.format_exc())
            self._failed(e)
            return
        self.status.configure(text=f"Restarting with Stage Chart {rel['version']} …")
        self.root.after(300, self.quit)

    def _failed(self, e):
        from tkinter import messagebox
        self.installing = False
        msg = str(e) if isinstance(e, updater.UpdateError) else f"The update didn't work ({e})."
        self.say("✗ " + msg, "bad")
        if self.dialog is not None:
            for b in self.buttons:
                b.configure(state="normal")
            self.status.configure(text=msg)
            messagebox.showwarning("Stage Chart", msg + f"\n\nDetails, if any, are in:\n{self.log_path}",
                                   parent=self.dialog)


def open_releases_page():
    webbrowser.open(updater.RELEASES_PAGE)

