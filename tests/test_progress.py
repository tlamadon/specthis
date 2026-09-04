"""The spinner and the meter: stderr only, and never load-bearing."""

from __future__ import annotations

import io
from collections import Counter
from pathlib import Path

from click.testing import CliRunner

from specthis import check, hashing, progress
from specthis.check import check_project
from specthis.cli import main
from specthis.parse import load_project

from .conftest import make_ready


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


class _Tty(io.StringIO):
    """A stream that claims to be a terminal, so the spinner draws."""

    def isatty(self) -> bool:
        return True


# ------------------------------------------------------------- metering


def test_meter_counts_repeat_reads_apart(root: Path) -> None:
    """The number that explains a slow project: how much of the hashing
    was a file read for the second time."""
    project = load_project(root)
    with progress.watch(io.StringIO()) as w:
        w.phase("deriving")
        check_project(project)
    m = w.meter
    assert m.calls > 0 and m.files > 0
    assert m.calls == m.files + m.repeat_calls
    # a bound script is digested twice — once for the code manifest,
    # once as a dependency in the input table
    assert m.repeat_calls > 0
    assert m.nbytes > 0 and m.elapsed > 0


def test_the_package_blob_is_hashed_once_not_once_per_entry(root: Path) -> None:
    """`code_sha` and `expected_inputs` both need the blob and both run
    per entry — the direct call re-read every package file `2 x n` times
    and was half the wall clock of a big `check`."""
    counts: Counter = Counter()
    with hashing.observing(lambda p, n, s: counts.update([p.name])):
        check_project(load_project(root))
    assert counts["helpers.py"] == 1, "the package blob was rebuilt per entry"


def test_one_derivation_is_one_moment_but_a_reload_re_hashes(root: Path) -> None:
    """Both halves of the memo's contract: stable within a load, gone
    on the next one — which is the re-load `serve` does on every edit."""
    project = load_project(root)
    before = check.package_blob(project)
    (root / "src/pkg/helpers.py").write_text("X = 2\n")
    assert check.package_blob(project) == before
    assert check.package_blob(load_project(root)) != before


def test_observer_is_uninstalled_after_the_block(root: Path) -> None:
    seen: list = []
    with hashing.observing(lambda p, n, s: seen.append(p)):
        hashing.file_sha(root / "scripts/fit_alpha.py")
    assert len(seen) == 1
    hashing.file_sha(root / "scripts/fit_alpha.py")
    assert len(seen) == 1, "the hook outlived its block"


def test_observer_is_uninstalled_after_an_exception(root: Path) -> None:
    try:
        with hashing.observing(lambda p, n, s: None):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert hashing._observer is None


def test_digests_are_unchanged_while_observed(root: Path) -> None:
    path = root / "scripts/fit_alpha.py"
    plain = hashing.file_sha(path)
    with hashing.observing(lambda p, n, s: None):
        watched = hashing.file_sha(path)
    assert plain == watched


# -------------------------------------------------------------- drawing


def test_spinner_stays_silent_below_the_grace_period(root: Path) -> None:
    stream = _Tty()
    with progress.watch(stream) as w:
        w.phase("deriving")
        check_project(load_project(root))
    assert stream.getvalue() == "", "a fast project must not flicker"


def test_spinner_never_writes_to_a_pipe(root: Path, monkeypatch) -> None:
    """Not a terminal: no thread, no frames, but the meter still runs."""
    monkeypatch.setattr(progress, "GRACE", 0.0)
    stream = io.StringIO()  # plain StringIO — isatty() is False
    with progress.watch(stream) as w:
        w.phase("deriving")
        w.tick("fit-alpha", 0, 3)
        check_project(load_project(root))
    assert stream.getvalue() == ""
    assert w.meter.calls > 0


def test_width_of_zero_does_not_eat_the_last_character() -> None:
    """An unsized pty reports zero columns; `text[:-1]` would silently
    drop a character from every frame."""
    w = progress.Watch(_Tty())
    assert w._width() >= 79


# ------------------------------------------------------------------ cli


def test_timing_goes_to_stderr_and_never_into_the_pipe(root: Path) -> None:
    make_ready(root)
    result = CliRunner().invoke(main, ["status", "--timing", "--path", str(root)])
    assert result.exit_code == 0
    assert "timing" not in result.stdout
    assert result.stdout.splitlines()[0].startswith("vouch tree")
    assert "timing" in result.stderr and "digests" in result.stderr


def test_fast_status_says_nothing_about_its_own_speed(root: Path) -> None:
    make_ready(root)
    result = CliRunner().invoke(main, ["status", "--path", str(root)])
    assert result.exit_code == 0
    assert result.stderr == ""
