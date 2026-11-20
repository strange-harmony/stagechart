"""Open the real Stage Chart window, convert a dropped PDF and a whole Planning Center set (against
tests/fake_pco.py), and check what lands on disk. Also checks the token store round trip.

    python tests/window_check.py SAMPLE.pdf          (needs a display; CI uses xvfb on Linux)

Used by tests/test_window.py and, inside the built apps on a real Mac and Windows PC, by
tests/smoke_installed.py. Exits non-zero with a message if anything is wrong.
"""
import glob
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def check(sample, timeout=180):
    work = tempfile.mkdtemp()
    os.environ["STAGECHART_DATA_DIR"] = os.path.join(work, "data")
    os.environ["STAGECHART_SECRET_NAME"] = "Stage Chart - test token (safe to delete)"
    import pco
    import secrets_store
    import window
    from fake_pco import FakePCO

    # --- the token store (keychain / Credential Manager / file) keeps and forgets a token
    where = secrets_store.save("test-id", "test-secret")
    got = secrets_store.load()
    secrets_store.forget()
    gone = secrets_store.load()
    print("token store:", where, "ok" if got == ("test-id", "test-secret") and gone is None else "FAILED")
    if got != ("test-id", "test-secret") or gone is not None:
        raise SystemExit(f"FAILED: token store gave {got!r}, then {gone!r} after forget")

    # --- the window
    drop = os.path.join(work, "dropped")
    os.makedirs(drop)
    dropped = shutil.copy(sample, os.path.join(drop, os.path.basename(sample)))
    fake = FakePCO(sample)
    win = window.StageChartWindow(window.Platform(print), [dropped], smoke=True)
    win.settings["pc_folder"] = os.path.join(work, "sets")
    root = win.root
    print("drag and drop:", "on" if win.dnd else "off")
    win.client = pco.Client("id", "secret", opener=fake.open, sleep=lambda s: None)
    win._load_pc()
    state = {"set": False, "error": None}
    t0 = time.time()

    def tick():
        try:
            if not state["set"] and win.pc_state == "connected" and win.plan:
                state["set"] = True
                win.convert_set()
            done_set = any(s.get("finished") for s in win.sets.values())
            rows_done = win.rows and all(r.finished for r in win.rows)
            if state["set"] and done_set and rows_done and not any(r.state == "busy" for r in win.rows):
                root.after(800, root.destroy)              # the whole-set PDF is written just after
                return
            if time.time() - t0 > timeout:
                state["error"] = "timed out: " + ", ".join(f"{r.name}={r.state}" for r in win.rows)
                root.destroy()
                return
        except Exception as e:                              # pragma: no cover
            state["error"] = repr(e)
            root.destroy()
            return
        root.after(200, tick)
    root.after(300, tick)
    win.settings_win = None
    root.after(1500, win.open_settings)                    # the Settings window must build too
    root.after(2500, lambda: win.settings_win and win.settings_win.close())
    root.mainloop()
    if state["error"]:
        raise SystemExit("FAILED: " + state["error"])

    made = glob.glob(os.path.join(drop, "*Stage Chart*.pdf"))
    sets = glob.glob(os.path.join(work, "sets", "*"))
    print("dropped chart:", [os.path.basename(m) for m in made])
    if len(made) != 1:
        raise SystemExit("FAILED: the dropped PDF wasn't converted next to its original")
    if len(sets) != 1:
        raise SystemExit(f"FAILED: expected one plan folder, got {sets}")
    files = sorted(os.listdir(sets[0]))
    print("plan folder:", os.path.basename(sets[0]), files)
    charts = [f for f in files if f[:2].isdigit() and "Stage Chart" in f]
    whole = [f for f in files if f.endswith("Whole Set.pdf")]
    originals = os.listdir(os.path.join(sets[0], "Originals"))
    if len(charts) != 4 or len(whole) != 1 or len(originals) != 4:
        raise SystemExit(f"FAILED: expected 4 numbered charts, 4 originals and a whole-set PDF; got {files}, "
                         f"{originals}")
    if ".converting" in files:
        raise SystemExit("FAILED: left a .converting folder behind")
    from pypdf import PdfReader
    pages = len(PdfReader(os.path.join(sets[0], whole[0])).pages)
    single = sum(len(PdfReader(os.path.join(sets[0], c)).pages) for c in charts)
    print("whole set pages:", pages)
    if pages != single:
        raise SystemExit(f"FAILED: whole set has {pages} pages, the charts have {single}")
    states = {r.name: r.state for r in win.rows}
    print("rows:", states)
    if states.get("Come Thou Fount") != "check":          # plan says E, the chart is in D: flag, never transpose
        raise SystemExit("FAILED: a chart in the wrong key wasn't flagged")
    if os.path.getsize(sample) != os.path.getsize(dropped):
        raise SystemExit("FAILED: the dropped original changed")
    shutil.rmtree(work, ignore_errors=True)
    print("window check: all good")


if __name__ == "__main__":
    app = os.path.join(os.path.dirname(HERE), "app")
    if os.path.isdir(app) and app not in sys.path:
        sys.path.insert(0, app)
    check(sys.argv[1])
