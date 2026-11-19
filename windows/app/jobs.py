"""Conversion jobs, independent of any window or platform.

Every source of charts (PDFs the user picks today, Planning Center later) ends in the same place:
a list of local PDF paths handed to ConversionQueue.submit(). The queue converts them one at a
time on a worker thread with the unchanged stagechart.convert() and reports back through callbacks
that the window runs on its own thread.
"""
from __future__ import annotations

import os
import queue
import threading
import traceback
from dataclasses import dataclass, field

import stagechart


@dataclass
class Job:
    path: str                      # local PDF to convert (never modified)
    out_dir: str | None = None     # None: save next to the original
    label: str = ""                # what to call it in the log, e.g. a song title from a service plan
    origin: str = "file"           # "file" now; "planning_center" later


@dataclass
class Result:
    job: Job
    ok: bool
    out: str | None = None
    lines: list = field(default_factory=list)


def friendly_error(e: Exception) -> str:
    name = e.__class__.__name__
    if "Password" in name or "Encrypt" in name:
        return "The PDF is password-protected."
    if "Syntax" in name or "No /Root" in str(e):
        return "The file isn't a readable PDF."
    if isinstance(e, PermissionError):
        return "Windows wouldn't let Stage Chart save there. Try saving to another folder."
    return str(e) or name


def convert_job(job: Job, log_error=lambda text: None) -> Result:
    try:
        out, summary = stagechart.convert(job.path, job.out_dir)
        return Result(job, True, out, list(summary))
    except Exception as e:
        log_error(f"{job.path}\n{traceback.format_exc()}")
        name = job.label or os.path.basename(job.path)
        return Result(job, False, None, [f"{name}: couldn't convert. {friendly_error(e)}"])


class ConversionQueue:
    """Single worker thread. Callbacks are queued for the UI thread; call drain() from it."""

    def __init__(self, on_start, on_done, log_error=lambda text: None):
        self.on_start, self.on_done, self.log_error = on_start, on_done, log_error
        self._jobs: queue.Queue = queue.Queue()
        self._events: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, jobs):
        for j in jobs:
            self._jobs.put(j)

    def _run(self):
        while True:
            job = self._jobs.get()
            self._events.put((self.on_start, (job,)))
            self._events.put((self.on_done, (convert_job(job, self.log_error),)))

    def drain(self):
        try:
            while True:
                fn, args = self._events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
