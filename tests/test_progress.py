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


def test_a_derivation_reads_every_file_exactly_once(root: Path) -> None:
    """The memo's whole point. A script is code to `code_manifest` and a
    dependency to `expected_inputs`; a source entry's bytes are its
    code, its input table *and* its output. None of those call sites can
    see the others, so only a memo can make one path one read."""
    counts: Counter = Counter()
    with hashing.observing(lambda p, n, s, cached: cached or counts.update([p.name])):
        check_project(load_project(root))
    assert counts, "nothing was hashed at all"
    assert max(counts.values()) == 1, f"read twice: {[k for k, v in counts.items() if v > 1]}"


def test_the_meter_separates_reads_from_memo_hits(root: Path) -> None:
    project = load_project(root)
    with progress.watch(io.StringIO()) as w:
        w.phase("deriving")
        check_project(project)
    m = w.meter
    assert m.calls > 0 and m.files == m.calls, "a read that the memo should have served"
    assert m.repeat_calls == 0
    assert m.hits > 0, "the fixture digests some path from two call sites"
    assert m.nbytes > 0 and m.elapsed > 0


def test_the_memo_expires_with_the_derivation(root: Path) -> None:
    """Scope is one `check_project`, never a whole command. `build` hands
    work to a manager that writes outputs and then re-derives; a memo
    spanning that would answer with the pre-build bytes."""
    before = check_project(load_project(root))["fit-alpha"].code_sha
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    after = check_project(load_project(root))["fit-alpha"].code_sha
    assert after != before


def test_the_memo_is_not_installed_outside_a_derivation(root: Path) -> None:
    path = root / "scripts/fit_alpha.py"
    first = hashing.file_sha(path)
    path.write_text("# rewritten\n")
    assert hashing.file_sha(path) != first


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
    with hashing.observing(lambda p, n, s, cached: seen.append(p)):
        hashing.file_sha(root / "scripts/fit_alpha.py")
    assert len(seen) == 1
    hashing.file_sha(root / "scripts/fit_alpha.py")
    assert len(seen) == 1, "the hook outlived its block"


def test_observer_is_uninstalled_after_an_exception(root: Path) -> None:
    try:
        with hashing.observing(lambda p, n, s, cached: None):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert hashing._observer is None


def test_digests_are_unchanged_while_observed(root: Path) -> None:
    path = root / "scripts/fit_alpha.py"
    plain = hashing.file_sha(path)
    with hashing.observing(lambda p, n, s, cached: None):
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
