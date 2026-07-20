import json
from pathlib import Path

from click.testing import CliRunner

from specthis.check import Status, check_project
from specthis.cli import main
from specthis.ledger import read_runs, read_vouches
from specthis.parse import load_project

from .conftest import PY, COMPUTE_ALPHA, FIT_ALPHA_PY, fake_run, make_ready, vouch_ok, write


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def test_check_exit_codes_and_frontier(root: Path) -> None:
    # fresh project: every entry is unvouched (mind queue) and, being
    # mechanically runnable, never-run (machine queue) at once
    result = run_cli("check", "--path", str(root))
    assert result.exit_code == 1
    assert "definitions needing a mind" in result.output
    assert "unvouched" in result.output
    assert "realizations needing a machine" in result.output
    assert "never-run" in result.output

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
    # both trees are blocked upstream: the lineage has an uncertified
    # definition and a stale call
    assert "waiting on upstream: 2 (2 on minds, 2 on machines)" in result.output


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


def test_vouch_took_records_duration(root: Path) -> None:
    result = run_cli(
        "vouch", "fit-alpha", "--as", "reviewer", "--took", "212.4", "--path", str(root)
    )
    assert result.exit_code == 0, result.output
    assert read_vouches(root / "specs")["fit-alpha"].duration_seconds == 212.4
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "(took 3m 32s)" in result.output


def test_check_attributes_expiry_to_package_blob(root: Path) -> None:
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    write(root, "src/pkg/helpers.py", "X = 2\n")
    result = run_cli("check", "--path", str(root))
    assert "moved since vouch: code: package blob moved" in result.output
    assert "fit_alpha.py moved" not in result.output  # the script is innocent


def test_check_attributes_expiry_to_the_script(root: Path) -> None:
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    result = run_cli("check", "--path", str(root))
    assert "moved since vouch: code: scripts/fit_alpha.py moved" in result.output
    assert "package blob" not in result.output  # the blob is innocent


def test_status_attributes_spec_movement_relative_to_block(root: Path) -> None:
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    # prose outside the entry's ### block moves: file-level expiry, but
    # the diagnosis says the entry's own contract text is untouched
    outside = COMPUTE_ALPHA.replace(
        "Fit the alpha model per models.md.",
        "Fit the alpha model per models.md. Now with more prose.",
    )
    write(root, "specs/compute-alpha.md", outside)
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "moved since last vouch:" in result.output
    assert "compute-alpha.md moved outside this entry's block" in result.output

    # re-vouch at the new digests, then edit inside the block
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    inside = outside.replace(
        "The fit must converge and record its loss.",
        "The fit must converge quickly and record its loss.",
    )
    write(root, "specs/compute-alpha.md", inside)
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "this entry's block in compute-alpha.md moved" in result.output


def test_legacy_vouch_without_manifest_still_attributes_coarsely(root: Path) -> None:
    vouch_ok(root, "fit-alpha")  # writes a row without the decomposed fields
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    result = run_cli("check", "--path", str(root))
    assert "moved since vouch: code moved" in result.output  # coarse, not wrong


def test_run_records_duration_and_reports_time(root: Path) -> None:
    result = run_cli("run", "fit-alpha", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "recorded run of `fit-alpha` in " in result.output
    row = read_runs(root / "specs")["fit-alpha"]
    assert row.duration_seconds is not None and row.duration_seconds >= 0
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "(took " in result.output


def test_run_reports_output_reproduced_vs_moved(root: Path) -> None:
    make_ready(root)
    # deterministic script: a re-run reproduces identical bytes,
    # which cuts the downstream cascade — and says so
    result = run_cli("run", "fit-alpha", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "output unchanged — downstream claims unaffected" in result.output

    # change what the script writes: the output moves, consumers named
    write(root, "scripts/fit_alpha.py", FIT_ALPHA_PY.replace('"loss": 1.0', '"loss": 2.0'))
    result = run_cli("run", "fit-alpha", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "output moved" in result.output
    assert "fit-beta" in result.output  # the now-stale consumer is named


def test_run_stale_narrates_plan_and_progress(root: Path) -> None:
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)  # all vouched, none run: everything STALE
    result = run_cli("run", "--stale", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "3 entries in the machine queue: fit-alpha -> fit-beta -> fig-beta" in result.output
    assert "[1/3]" in result.output
    assert "[3/3]" in result.output
    assert "rebuilt 3 entries in " in result.output


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

    # mechanical policy: unvouched is no bar to compute — the machine
    # rebuilds while a mind audits the definition in parallel
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    result = run_cli("run", "--stale", "--path", str(root))
    assert result.exit_code == 0
    assert "rebuilt 1" in result.output
    assert "skipped" not in result.output


def test_run_stale_skips_rejected_definitions(root: Path) -> None:
    """The one certification state that gates compute: a machine must
    not realize a definition a mind refused."""
    from specthis.check import code_sha
    from specthis.ledger import Vouch, record_vouch

    make_ready(root)
    project = load_project(root)
    e = project.entries["fit-alpha"]
    c = code_sha(project, e)
    assert c is not None
    record_vouch(
        project.specs_dir,
        "fit-alpha",
        Vouch(
            spec_sha=e.spec.spec_sha,
            code_sha=c,
            verdict="rejected",
            attester="critic",
            vouched="2026-01-02T00:00:00+00:00",
        ),
    )
    write(root, "hut.fit-alpha.json", '{"backend": "pbs"}\n')  # stale, rejection stands
    result = run_cli("run", "--stale", "--path", str(root))
    assert result.exit_code == 0
    assert "rebuilt 0" in result.output
    assert "skipped fit-alpha: rejected (needs a mind, not a machine)" in result.output


HANDSHAKE_PY = """\
import pathlib, sys, time
me, other = sys.argv[1], sys.argv[2]
pathlib.Path("results").mkdir(exist_ok=True)
pathlib.Path(f"results/{me}.started").write_text("x")
deadline = time.time() + 30
while not pathlib.Path(f"results/{other}.started").exists():
    if time.time() > deadline:
        raise SystemExit(f"never saw {other} start — the queue ran serially")
    time.sleep(0.05)
pathlib.Path(f"results/{me}.json").write_text("{}")
"""


def add_handshake_pair(root: Path) -> None:
    """Two independent quick entries whose scripts each wait to see the
    other one start: both finish only if the scheduler truly overlaps them."""
    for name, other in (("left", "right"), ("right", "left")):
        write(
            root,
            f"specs/compute-{name}.md",
            f"""\
---
name: compute-{name}
kind: compute
tier: quick
---

# {name}

## Entry

### fit-{name}

Handshake with fit-{other}.

Output: `results/{name}.json`
""",
        )
        with open(root / "specs/bindings.toml", "a", encoding="utf-8") as f:
            f.write(
                f'\n[entries.fit-{name}]\n'
                f'scripts = ["scripts/handshake.py"]\n'
                f"run = '{PY} scripts/handshake.py {name} {other}'\n"
            )
    write(root, "scripts/handshake.py", HANDSHAKE_PY)


def test_run_stale_parallel_overlaps_independent_entries(root: Path) -> None:
    make_ready(root)  # the original chain is READY: only the pair queues
    add_handshake_pair(root)
    vouch_ok(root, "fit-left")
    vouch_ok(root, "fit-right")
    result = run_cli("run", "--stale", "-p", "2", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "(up to 2 in parallel)" in result.output
    assert "rebuilt 2 entries" in result.output
    assert (root / "results/left.json").exists()
    assert (root / "results/right.json").exists()


def test_run_stale_parallel_respects_chain_order(root: Path) -> None:
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)  # a strict chain: workers must wait on upstream claims
    result = run_cli("run", "--stale", "-p", "4", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "rebuilt 3 entries" in result.output
    reports = check_project(load_project(root))
    assert {r.status for r in reports.values()} == {Status.READY}


def test_run_parallel_requires_stale(root: Path) -> None:
    result = run_cli("run", "fit-alpha", "-p", "2", "--path", str(root))
    assert result.exit_code != 0
    assert "--stale" in result.output


def test_run_stale_parallel_failure_schedules_nothing_new(root: Path) -> None:
    (root / "scripts/fit_alpha.py").write_text("raise SystemExit(3)\n")
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)  # vouched at the failing digests: all STALE
    result = run_cli("run", "--stale", "-p", "4", "--path", str(root))
    assert result.exit_code != 0
    assert "exit 3" in result.output
    assert "1 entry failed" in result.output
    assert not (root / "specs/runs.toml").exists(), "failed runs record nothing"


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
