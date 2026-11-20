"""Stage Chart window: pick (or drop) chord chart PDFs and save stage charts next to them."""
import os
import queue
import subprocess
import sys
import threading
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


def about(root):
    from tkinter import messagebox
    from version import VERSION
    messagebox.showinfo("About Stage Chart",
                        f"Stage Chart {VERSION}\n\nLight mode, two columns, 17pt lyrics, original key, page count "
                        "matched where possible, repeats shown once with ×2, bridges printed in order with cues, "
                        "slash chords like D/F#.\n\nFont: Carlito (SIL Open Font License).", parent=root)


# --------------------------------------------------------------------------------------------
# Tk window
# --------------------------------------------------------------------------------------------
def run_window(initial):
    import tkinter as tk
    from tkinter import filedialog, font

    root = tk.Tk()
    root.title("Stage Chart")
    root.geometry("560x430")
    root.minsize(460, 340)
    root.configure(bg="#f5f5f7")

    big = font.Font(family="Helvetica", size=20, weight="bold")
    body = font.Font(family="Helvetica", size=13)
    small = font.Font(family="Helvetica", size=12)

    tk.Label(root, text="Stage Chart", font=big, bg="#f5f5f7", fg="#1d1d1f").pack(pady=(18, 2))
    tk.Label(root, text="Turns a chord chart PDF into a light, two-column, 17pt stage chart.\n"
                        "The stage chart is saved in the same folder as the original.\n"
                        "The original PDF is never changed.",
             font=body, bg="#f5f5f7", fg="#515154", justify="center").pack(pady=(0, 10))

    last = {"out": None}
    busy = {"n": 0}
    btns = tk.Frame(root, bg="#f5f5f7")
    btns.pack(pady=4)

    logbox = tk.Text(root, height=10, wrap="word", font=small, relief="flat", bg="white", fg="#1d1d1f",
                     padx=10, pady=8, highlightthickness=1, highlightbackground="#d2d2d7")
    logbox.pack(fill="both", expand=True, padx=18, pady=(8, 6))
    logbox.tag_configure("ok", foreground="#1a7f37")
    logbox.tag_configure("bad", foreground="#c62828")
    logbox.insert("end", "Click Choose PDFs, or drop PDFs onto the Stage Chart icon in the Dock.\n")
    logbox.configure(state="disabled")

    def say(text, tag=None):
        logbox.configure(state="normal")
        logbox.insert("end", text + "\n", tag)
        logbox.see("end")
        logbox.configure(state="disabled")

    show_btn = tk.Button(btns, text="Show in Finder", font=body, state="disabled",
                         command=lambda: last["out"] and subprocess.run(["open", "-R", last["out"]]))
    open_btn = tk.Button(btns, text="Open Chart", font=body, state="disabled",
                         command=lambda: last["out"] and subprocess.run(["open", last["out"]]))

    events = queue.Queue()      # worker thread -> window (Tk is only touched on the main thread)

    def pump():
        try:
            while True:
                fn, args = events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        root.after(100, pump)

    def finished(ok, out, summary):
        if ok:
            say(f"✓ Saved “{os.path.basename(out)}”", "ok")
            for s in summary:
                say("    " + s)
            last["out"] = out
            show_btn.configure(state="normal")
            open_btn.configure(state="normal")
        else:
            for s in summary:
                say("✗ " + s, "bad")

    def process(paths):
        pdfs = [p for p in paths if p.lower().endswith(".pdf")]
        for p in paths:
            if p not in pdfs:
                say(f"✗ {os.path.basename(p)}: only PDF files can be converted.", "bad")
        if not pdfs:
            return

        def work():
            busy["n"] += 1
            try:
                for p in pdfs:
                    events.put((say, (f"Converting {os.path.basename(p)} …",)))
                    events.put((finished, convert_one(p)))
            finally:
                busy["n"] -= 1

        threading.Thread(target=work, daemon=True).start()

    def choose():
        paths = filedialog.askopenfilenames(title="Choose chord chart PDFs",
                                            filetypes=[("PDF files", "*.pdf"), ("PDF files", "*.PDF")])
        if paths:
            process(list(paths))

    tk.Button(btns, text="Choose PDFs…", font=body, command=choose, default="active").pack(side="left", padx=4)
    show_btn.pack(side="left", padx=4)
    open_btn.pack(side="left", padx=4)

    # files dropped on the app or Dock icon arrive as an "open documents" event
    try:
        root.createcommand("::tk::mac::OpenDocument", lambda *args: process(list(args)))
    except Exception:
        pass
    try:
        root.createcommand("tk::mac::Quit", root.destroy)
    except Exception:
        pass

    # updates: "Check for Updates…" in the Stage Chart menu, plus a quiet check once a day
    try:
        import update_ui
        upd = update_ui.UpdateUI(root, say=say, log_path=LOG, log_error=log_error,
                                 busy=lambda: busy["n"] > 0, quit=root.destroy)
        menubar = tk.Menu(root)
        app_menu = tk.Menu(menubar, name="apple", tearoff=0)
        app_menu.add_command(label="About Stage Chart", command=lambda: about(root))
        app_menu.add_command(label="Check for Updates…", command=upd.check_now)
        app_menu.add_separator()
        menubar.add_cascade(menu=app_menu)
        root.config(menu=menubar)
        upd.start()
    except Exception:
        log_error("updates unavailable:\n" + traceback.format_exc())

    root.after(100, pump)
    if initial:
        root.after(200, lambda: process(initial))
    root.lift()
    root.after(300, lambda: root.attributes("-topmost", False))
    root.mainloop()


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
