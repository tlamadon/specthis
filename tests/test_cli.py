import json
from pathlib import Path

from click.testing import CliRunner

from specthis.check import Status, check_project
from specthis.cli import main
from specthis.parse import load_project

from .conftest import fake_run, make_ready, vouch_ok, write


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def test_check_exit_codes_and_frontier(root: Path) -> None:
    result = run_cli("check", "--path", str(root))
    assert result.exit_code == 1
    assert "frontier" in result.output
    assert "audit needed" in result.output

    make_ready(root)
    result = run_cli("check", "--path", str(root))
    assert result.exit_code == 0
    assert result.output.strip() == "ready: 3/3"


def test_check_summarizes_downstream(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    result = run_cli("check", "--path", str(root))
    assert result.exit_code == 1
    assert "fit-alpha" in result.output
    assert "fit-beta" not in result.output  # downstream is a count, not a row
    assert "2 upstream-unverified" in result.output


def test_status_detail_names_the_moved_input(root: Path) -> None:
    make_ready(root)
    write(root, "hut.fit-alpha.json", '{"backend": "pbs"}\n')
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert result.exit_code == 0
    assert "stale" in result.output
    assert "hut.fit-alpha.json" in result.output


def test_vouch_requires_attester(root: Path) -> None:
    assert run_cli("vouch", "fit-alpha", "--path", str(root)).exit_code != 0


def test_vouch_writes_only_vouches(root: Path) -> None:
    result = run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    assert result.exit_code == 0
    assert (root / "specs/vouches.toml").exists()
    assert not (root / "specs/runs.toml").exists()


def test_vouch_refuses_missing_code(root: Path) -> None:
    (root / "scripts/fit_alpha.py").unlink()
    result = run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    assert result.exit_code != 0
    assert "nothing to judge" in result.output


def test_vouch_ok_refused_over_standing_rejection(root: Path) -> None:
    assert run_cli(
        "vouch", "fit-alpha", "--as", "reviewer", "--reject", "--note", "bad loss",
        "--path", str(root),
    ).exit_code == 0
    result = run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    assert result.exit_code != 0
    assert "standing rejection" in result.output


def test_vouch_notes_unverified_upstream(root: Path) -> None:
    result = run_cli("vouch", "fit-beta", "--as", "reviewer", "--path", str(root))
    assert result.exit_code == 0
    assert "recorded ok" in result.output
    assert "upstream not yet verified (fit-alpha)" in result.output


def test_vouch_no_upstream_note_when_chain_ready(root: Path) -> None:
    make_ready(root)
    result = run_cli("vouch", "fit-beta", "--as", "reviewer", "--path", str(root))
    assert result.exit_code == 0
    assert "upstream" not in result.output

    # entries without consumes never get the note
    result = run_cli("vouch", "fit-alpha", "--as", "another", "--path", str(root))
    assert result.exit_code == 0
    assert "upstream" not in result.output


def test_run_records_derived_claim_only(root: Path) -> None:
    vouch_before = None  # no vouches file yet
    result = run_cli("run", "fit-alpha", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert (root / "results/alpha/fit.json").exists()
    assert (root / "specs/runs.toml").exists()
    assert not (root / "specs/vouches.toml").exists(), "run must never write vouches"
    assert vouch_before is None


def test_run_refuses_when_upstream_never_ran(root: Path) -> None:
    result = run_cli("run", "fit-beta", "--path", str(root))
    assert result.exit_code != 0
    assert "fit-alpha" in result.output


def test_run_failure_records_nothing(root: Path) -> None:
    (root / "scripts/fit_alpha.py").write_text("raise SystemExit(3)\n")
    result = run_cli("run", "fit-alpha", "--path", str(root))
    assert result.exit_code != 0
    assert not (root / "specs/runs.toml").exists()


def test_run_stale_rebuilds_in_topo_order_and_skips_minds(root: Path) -> None:
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)  # all vouched, none run: everything STALE
    result = run_cli("run", "--stale", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "rebuilt 3" in result.output
    reports = check_project(load_project(root))
    assert {r.status for r in reports.values()} == {Status.READY}

    # upstream re-run cascades: touch alpha's output and re-record it
    write(root, "results/alpha/fit.json", '{"loss": 7.0}')
    fake_run(root, "fit-alpha", execute=False)
    result = run_cli("run", "--stale", "--path", str(root))
    assert result.exit_code == 0
    assert "rebuilt 2" in result.output  # beta then fig-beta, topo order

    # an unvouched entry is a mind's problem, not the machine's
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    result = run_cli("run", "--stale", "--path", str(root))
    assert "skipped fit-alpha: audit needed" in result.output


def test_init_scaffold_passes_check(tmp_path: Path) -> None:
    # The bundled templates must parse under the shipping parser.
    assert run_cli("init", "--path", str(tmp_path)).exit_code == 0
    result = run_cli("check", "--path", str(tmp_path))
    assert result.exit_code == 0, result.output
    assert "ready: 0/0" in result.output


def test_migrate_dry_run_then_write(root: Path) -> None:
    lock = {
        "fit-alpha": {
            "inputs_certified": {"scripts/fit_alpha.py": "deadbeef"},
            "ts": "2025-12-01T00:00:00+00:00",
        },
        "ghost-entry": {"inputs_certified": {}},
    }
    write(root, "specs/_lock.json", json.dumps(lock))

    result = run_cli("migrate", "--path", str(root))
    assert result.exit_code == 0
    assert "would import 1" in result.output
    assert "ghost-entry" in result.output  # skipped, with a reason
    assert "vouches imported: 0" in result.output
    assert not (root / "specs/runs.toml").exists()  # dry run wrote nothing

    result = run_cli("migrate", "--write", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert (root / "specs/runs.toml").exists()
    assert not (root / "specs/vouches.toml").exists()

    # migrated row is honest: entry is not READY, it needs vouch + re-run
    vouch_ok(root, "fit-alpha")
    assert check_project(load_project(root))["fit-alpha"].status is Status.STALE

    # refuses to clobber without --force
    result = run_cli("migrate", "--write", "--path", str(root))
    assert "runs.toml row exists" in result.output
