"""Liveness while a derivation runs, and an account of where it went.

`check_project` re-reads and re-hashes every byte the project declares —
that is the no-mtime doctrine (§10) working, not a bug. The cost of it
is that on a real project a verb can sit silent for seconds with nothing
to distinguish slow work from a hung process, and when it *is* slow,
nothing says which part was slow. This module is those two answers: a
spinner while the work runs, and a breakdown afterwards.

Everything here is a **stderr** fact. Nothing touches stdout, so
`specthis status | grep` still sees exactly the rows and a redirected
run produces the same bytes as a piped one. The spinner draws only when
stderr is a terminal — which is what keeps a CI log free of half-erased
frames — and stays silent for the first fraction of a second, so a
project that derives in 60 ms never flickers.

The meter is separate from the spinner and always runs: a piped
`--timing` still reports, it just does so without ever having drawn.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from . import hashing

#: Draw nothing below this many seconds. A project that derives in a
#: blink must not flash a spinner at you; one that takes five seconds
#: must not look hung.
GRACE = 0.25

#: Redraw interval. Fast enough to read as alive, slow enough that
#: digesting a 10 GB output does not spend its time writing escape
#: codes at a terminal nobody is watching that closely.
FRAME = 0.1

FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

#: A derivation slower than this explains itself in one line without
#: being asked. Below it the cost is not worth a word, and a verb that
#: comments on its own speed every time is noise.
CHATTY = 1.0


@dataclass
class Meter:
    """What the work cost: wall time per phase, and the file digests
    underneath all of them.

    Digests are counted apart from the phases because they are the
    answer. A derivation is a hashing loop with bookkeeping around it,
    so a phase breakdown alone says "it was slow in the part that does
    everything"; the number that actually explains a slow project is
    how much of the hashing was a file read for the second time.
    """

    phases: dict[str, float] = field(default_factory=dict)
    calls: int = 0
    seconds: float = 0.0
    nbytes: int = 0
    repeat_calls: int = 0
    repeat_seconds: float = 0.0
    _seen: set[str] = field(default_factory=set)

    @property
    def files(self) -> int:
        """Distinct files digested — the number `calls` would be if
        nothing were hashed twice."""
        return len(self._seen)

    @property
    def elapsed(self) -> float:
        return sum(self.phases.values())

    def digest(self, path: Path, nbytes: int, seconds: float) -> None:
        """Record one file digest. Installed as the hashing observer."""
        self.calls += 1
        self.nbytes += nbytes
        self.seconds += seconds
        key = str(path)
        if key in self._seen:
            self.repeat_calls += 1
            self.repeat_seconds += seconds
        else:
            self._seen.add(key)


def _secs(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s"


def _size(n: int) -> str:
    if n < 1_000_000:
        return f"{n / 1_000:.0f} kB"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f} MB"
    return f"{n / 1_000_000_000:.2f} GB"


def report(meter: Meter) -> list[str]:
    """The full `--timing` breakdown, in the order the phases ran."""
    phases = " · ".join(f"{label} {_secs(t)}" for label, t in meter.phases.items())
    lines = [f"timing   {phases}  —  {_secs(meter.elapsed)} total"]
    if meter.calls:
        lines.append(
            f"digests  {meter.calls:,} reads over {meter.files:,} files · "
            f"{_size(meter.nbytes)} · {_secs(meter.seconds)}"
        )
    if meter.repeat_calls:
        share = f", {meter.repeat_seconds / meter.elapsed:.0%} of the run" if meter.elapsed else ""
        lines.append(
            f"         {meter.repeat_calls:,} of those re-read a file already hashed "
            f"— {_secs(meter.repeat_seconds)}{share}"
        )
    return lines


def summary(meter: Meter) -> str:
    """The single line a slow derivation volunteers, unasked."""
    parts = [f"derived in {_secs(meter.elapsed)}"]
    if meter.calls:
        parts.append(
            f"{_secs(meter.seconds)} hashing {meter.files:,} files ({_size(meter.nbytes)})"
        )
    if meter.repeat_calls:
        parts.append(f"{meter.repeat_calls:,} repeat reads")
    tail = f", {parts[2]}" if len(parts) > 2 else ""
    return " — ".join(parts[:2]) + tail + "  ·  --timing for the breakdown"


class Watch:
    """A spinner on stderr, and the meter it is spinning for.

    The drawing runs on its own thread rather than off the work's own
    ticks, because the case worth covering is a single entry digesting
    one enormous file: tick-driven output would freeze exactly when the
    user most needs to see something moving.
    """

    def __init__(self, stream: IO[str] | None = None) -> None:
        self.meter = Meter()
        self._stream = sys.stderr if stream is None else stream
        self._live = bool(getattr(self._stream, "isatty", lambda: False)())
        self._label = ""
        self._detail = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = time.perf_counter()
        self._phase_start = self._started
        self._drawn = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------- recording

    def phase(self, label: str) -> None:
        """Close the running phase and open a new one."""
        now = time.perf_counter()
        with self._lock:
            if self._label:
                prior = self.meter.phases.get(self._label, 0.0)
                self.meter.phases[self._label] = prior + now - self._phase_start
            self._label, self._detail, self._phase_start = label, "", now

    def tick(self, entry: str, done: int, total: int) -> None:
        """The derivation's liveness hook — one call per entry, before
        the work for it starts."""
        with self._lock:
            self._detail = f"{done + 1}/{total}  {entry}"

    # ---------------------------------------------------------- drawing

    def start(self) -> None:
        if not self._live:
            return
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.phase("")  # bank the last phase
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self._erase()

    def _spin(self) -> None:
        frame = 0
        while not self._stop.wait(FRAME):
            if time.perf_counter() - self._started < GRACE:
                continue
            with self._lock:
                label, detail = self._label, self._detail
            if not label:
                continue
            self._draw(f"{FRAMES[frame % len(FRAMES)]} {label}  {detail}".rstrip())
            frame += 1

    def _width(self) -> int:
        """Columns on the stream we actually draw to.

        Asking :mod:`shutil` would measure *stdout*, which is routinely
        a pipe while stderr is still a terminal — the exact case this
        spinner exists for. Zero is what an unsized pty reports, and it
        is treated as unknown rather than used: ``text[:-1]`` silently
        eats the last character of every frame.
        """
        try:
            columns = os.get_terminal_size(self._stream.fileno()).columns
        except (OSError, ValueError, AttributeError):
            columns = 0
        if columns <= 0:  # an unsized pty reports zero, and so does a failed ioctl
            columns = shutil.get_terminal_size((80, 24)).columns
        return (columns if columns > 0 else 80) - 1

    def _draw(self, text: str) -> None:
        self._stream.write("\r\x1b[K" + text[: self._width()])
        self._stream.flush()
        self._drawn = True

    def _erase(self) -> None:
        if not self._drawn:
            return
        self._stream.write("\r\x1b[K")
        self._stream.flush()
        self._drawn = False


@contextmanager
def watch(stream: IO[str] | None = None) -> Iterator[Watch]:
    """Spin on stderr while the block runs, metering every digest.

    The `Watch` outlives the block on purpose: a caller reads
    ``w.meter`` afterwards, so the timing report lands *below* the real
    output rather than racing the spinner for the same line.
    """
    w = Watch(stream)
    with hashing.observing(w.meter.digest):
        w.start()
        try:
            yield w
        finally:
            w.close()
