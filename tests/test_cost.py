"""Machine cost: CPU seconds and where the work happened.

Both are **claim metadata** — they enter no signature and move no
digest — and both are *declared*, never inferred. These tests pin that
boundary as much as the arithmetic.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from specthis.check import check_project, locality_of, spending
from specthis.cli import main
from specthis.ledger import Run, read_runs, record_run
from specthis.parse import load_project

from .conftest import make_ready, write


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def _stamp(root: Path, entry: str, **fields) -> None:
    """Rewrite one run row's cost metadata, leaving its digests alone."""
    runs = read_runs(root / "specs")
    row = runs[entry]
    record_run(root / "specs", entry, Run(**{**row.__dict__, **fields}))


# ------------------------------------------------------------- recording


def test_cost_metadata_moves_no_digest(root: Path) -> None:
    """The whole reason these fields are allowed to exist."""
    make_ready(root)
    before = check_project(load_project(root))["fit-alpha"]
    _stamp(root, "fit-alpha", cpu_seconds=3600.0, where="remote")
    after = check_project(load_project(root))["fit-alpha"]
    assert after.realization is before.realization
    assert after.run is not None and after.run.signature == before.run.signature


def test_record_declares_locality_and_cpu(root: Path) -> None:
    write(root, "results/alpha/fit.json", '{"loss": 1.0}')
    result = run_cli(
        "record", "fit-alpha", "--where", "remote", "--cpu", "7200", "--path", str(root)
    )
    assert result.exit_code == 0, result.output
    row = read_runs(root / "specs")["fit-alpha"]
    assert row.where == "remote" and row.cpu_seconds == 7200.0


def test_record_leaves_locality_unset_rather_than_guessing(root: Path) -> None:
    write(root, "results/alpha/fit.json", '{"loss": 1.0}')
    assert run_cli("record", "fit-alpha", "--path", str(root)).exit_code == 0
    assert read_runs(root / "specs")["fit-alpha"].where is None


def test_record_refuses_a_locality_outside_the_vocabulary(root: Path) -> None:
    result = run_cli("record", "fit-alpha", "--where", "slurm", "--path", str(root))
    assert result.exit_code != 0


# ------------------------------------------------------------ resolution


def test_a_rows_own_word_wins_over_the_executor_map(root: Path) -> None:
    make_ready(root)
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[executors]\ntest-harness = "local"\n')
    _stamp(root, "fit-alpha", executor="test-harness", where="remote")
    project = load_project(root)
    assert locality_of(project, read_runs(root / "specs")["fit-alpha"]) == "remote"


def test_the_executor_map_classifies_rows_that_never_said(root: Path) -> None:
    """What lets a ledger written before the field existed still answer
    'how much of this ran off my machine'."""
    make_ready(root)
    row = read_runs(root / "specs")["fit-alpha"]
    assert row.where is None
    project = load_project(root)
    assert locality_of(project, row) == "unknown"

    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + f'\n[executors]\n"{row.executor}" = "remote"\n')
    assert locality_of(load_project(root), row) == "remote"


def test_an_unclassified_executor_stays_unknown(root: Path) -> None:
    make_ready(root)
    project = load_project(root)
    row = read_runs(root / "specs")["fit-alpha"]
    assert locality_of(project, row) == "unknown", "a guess would invent a fact"


def test_a_bad_executor_map_is_a_grammar_problem(root: Path) -> None:
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[executors]\nscripthut = "the cluster"\n')
    result = run_cli("lint", "--path", str(root))
    assert result.exit_code != 0
    assert "local, remote" in result.output


# ------------------------------------------------------------ aggregation


def test_spending_splits_by_place_and_counts_the_untimed(root: Path) -> None:
    make_ready(root)
    _stamp(root, "fit-alpha", where="remote", duration_seconds=120.0, cpu_seconds=3600.0)
    _stamp(root, "fit-beta", where="local", duration_seconds=60.0, cpu_seconds=60.0)
    _stamp(root, "fig-beta", where="local", duration_seconds=None)
    project = load_project(root)
    spend = spending(project, check_project(project))

    assert spend["remote"].runs == 1 and spend["remote"].cpu == 3600.0
    assert spend["local"].runs == 2 and spend["local"].wall == 60.0
    assert spend["local"].untimed == 1, "a total must never be quietly short"


def test_cpu_stays_none_rather_than_falling_back_to_wall(root: Path) -> None:
    """Wall and CPU differ by a factor nobody here can know; a number
    that might be either is worse than an absent one."""
    make_ready(root)
    _stamp(root, "fit-alpha", where="local", duration_seconds=90.0, cpu_seconds=None)
    project = load_project(root)
    assert spending(project, check_project(project))["local"].cpu is None


# ------------------------------------------------------------------- cli


def test_status_reports_machine_cost_split_by_place(root: Path) -> None:
    make_ready(root)
    _stamp(root, "fit-alpha", where="remote", duration_seconds=7200.0, cpu_seconds=36000.0)
    _stamp(root, "fit-beta", where="local", duration_seconds=600.0, cpu_seconds=600.0)
    out = run_cli("status", "--path", str(root)).output
    machines = next(line for line in out.splitlines() if line.startswith("machines"))
    assert "10h 10m cpu" in machines
    assert "remote 10h 00m cpu" in machines and "local 10m 00s cpu" in machines


def test_a_project_with_no_recorded_cost_stays_two_lines(root: Path) -> None:
    make_ready(root)
    assert len(run_cli("status", "--path", str(root)).output.splitlines()) == 2


def test_status_detail_names_the_cost_and_the_place(root: Path) -> None:
    make_ready(root)
    _stamp(root, "fit-alpha", where="remote", duration_seconds=60.0, cpu_seconds=1800.0)
    out = run_cli("status", "fit-alpha", "--path", str(root)).output
    run_line = next(line for line in out.splitlines() if line.startswith("run:"))
    assert "took 1m 00s" in run_line and "30m 00s cpu" in run_line and "remote" in run_line
