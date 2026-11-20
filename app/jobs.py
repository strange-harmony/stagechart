"""Conversion jobs, independent of any window or platform.

Every source of charts (PDFs dropped or chosen, or charts downloaded from a Planning Center plan) ends
in the same place: a list of Jobs handed to ConversionQueue.submit(). The queue converts them one at a
time on a worker thread with the unchanged stagechart.convert() and reports back through callbacks that
the window runs on its own thread (call drain() from it).
"""
from __future__ import annotations

import itertools
import queue
import re
import threading
import traceback
from dataclasses import dataclass, field

import stagechart

_ids = itertools.count(1)


@dataclass
class Job:
    path: str                      # local PDF to convert (never modified)
    out_dir: str | None = None     # None: save next to the original
    label: str = ""                # what to call it in the window, e.g. a song title from a service plan
    origin: str = "file"           # "file" or "planning_center"
    plan_key: str = ""             # Planning Center: the key the song is scheduled in
    set_id: str = ""               # Planning Center: which set conversion this belongs to
    id: int = field(default_factory=lambda: next(_ids))


@dataclass
class Result:
    job: Job
    ok: bool
    out: str | None = None
    lines: list = field(default_factory=list)
    key: str = ""                  # the chart's key, as printed on the stage chart
    pages: int = 0
    song: object = None            # stagechart.Song, for the "Last finished" preview


def friendly_error(e: Exception) -> str:
    name = e.__class__.__name__
    if "Password" in name or "Encrypt" in name:
        return "The PDF is password-protected."
    if "Syntax" in name or "No /Root" in str(e):
        return "The file isn't a readable PDF."
    if isinstance(e, PermissionError):
        return "Stage Chart wasn't allowed to save there. Try saving to another folder."
    if "chords or lyrics" in str(e):
        return "No text found. This looks like a scanned image."
    return str(e) or name


def convert_job(job: Job, log_error=lambda text: None) -> Result:
    try:
        out, summary = stagechart.convert(job.path, job.out_dir)
        m = re.search(r": key (\S+), (\d+) page", summary[0]) if summary else None
        key = m.group(1) if m and m.group(1) != "?" else ""
        pages = int(m.group(2)) if m else 0
        song = None
        try:
            song = stagechart.parse(job.path)          # only for the preview; the chart is already saved
        except Exception:
            pass
        return Result(job, True, out, list(summary), key=key, pages=pages, song=song)
    except Exception as e:
        log_error(f"{job.path}\n{traceback.format_exc()}")
        return Result(job, False, None, [friendly_error(e)])


class ConversionQueue:
    """Single worker thread. Callbacks are queued for the UI thread; call drain() from it."""

    def __init__(self, on_start, on_done, log_error=lambda text: None):
        self.on_start, self.on_done, self.log_error = on_start, on_done, log_error
        self._jobs: queue.Queue = queue.Queue()
        self._events: queue.Queue = queue.Queue()
        self.busy = 0
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, jobs):
        for j in jobs:
            self.busy += 1
            self._jobs.put(j)

    def _run(self):
        while True:
            job = self._jobs.get()
            self._events.put((self.on_start, (job,)))
            res = convert_job(job, self.log_error)
            self._events.put((self._finished, (res,)))

    def _finished(self, res):
        self.busy = max(0, self.busy - 1)
        self.on_done(res)

    def post(self, fn, *args):
        """Run fn(*args) on the UI thread at the next drain(). Safe from any thread."""
        self._events.put((fn, args))

    def drain(self):
        try:
            while True:
                fn, args = self._events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
