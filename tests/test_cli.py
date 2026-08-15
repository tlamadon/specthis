import json
from pathlib import Path

from click.testing import CliRunner

from specthis.check import Status, check_project
from specthis.cli import main
from specthis.ledger import read_vouches
from specthis.parse import load_project

from .conftest import (
    BINDINGS,
    COMPUTE_ALPHA,
    PY,
    make_ready,
    vouch_ok,
    write,
)


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
    write(root, "pipeline.toml", f'''
[steps.fit-alpha]
command = '{PY} scripts/fit_alpha.py'
deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json"]
outs    = ["results/alpha/fit.json"]
''')
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
    assert "moved since vouch: code: ~package blob" in result.output
    assert "fit_alpha.py moved" not in result.output  # the script is innocent


def test_check_attributes_expiry_to_the_script(root: Path) -> None:
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    result = run_cli("check", "--path", str(root))
    assert "moved since vouch: code: ~scripts/fit_alpha.py" in result.output
    assert "package blob" not in result.output  # the blob is innocent


def test_check_attributes_a_file_added_to_the_binding(root: Path) -> None:
    """A composed digest can only say "code moved"; the table says which
    file entered the entry's scope, and that it was never judged."""
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    write(root, "scripts/helpers.py", "def winsor(x, p): return x\n")
    write(root, "specs/bindings.toml", BINDINGS.replace(
        '[entries.fit-alpha]\nscripts = ["scripts/fit_alpha.py"]',
        '[entries.fit-alpha]\nscripts = ["scripts/fit_alpha.py", "scripts/helpers.py"]',
    ))
    result = run_cli("check", "--path", str(root))
    assert "moved since vouch: code: +scripts/helpers.py" in result.output
    assert "~scripts/fit_alpha.py" not in result.output  # untouched, and says so


def test_check_attributes_a_file_removed_from_the_binding(root: Path) -> None:
    run_cli("vouch", "fit-beta", "--as", "reviewer", "--path", str(root))
    write(root, "specs/bindings.toml", BINDINGS.replace(
        '[entries.fit-beta]\nscripts = ["scripts/fit_beta.py"]',
        '[entries.fit-beta]\nscripts = []',
    ))
    result = run_cli("check", "--path", str(root))
    assert "-scripts/fit_beta.py" in result.output or "unimplemented" in result.output


def test_spec_prose_outside_the_block_does_not_expire_the_vouch(root: Path) -> None:
    """A vouch's subject is the entry's own block, never the whole file."""
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    outside = COMPUTE_ALPHA.replace(
        "Fit the alpha model per models.md.",
        "Fit the alpha model per models.md. Now with more prose.",
    )
    write(root, "specs/compute-alpha.md", outside)
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "certified" in result.output
    assert "moved since last vouch:" not in result.output


def test_status_attributes_spec_movement_inside_the_block(root: Path) -> None:
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    inside = COMPUTE_ALPHA.replace(
        "The fit must converge and record its loss.",
        "The fit must converge quickly and record its loss.",
    )
    write(root, "specs/compute-alpha.md", inside)
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "moved since last vouch:" in result.output
    assert "this entry's block in compute-alpha.md moved" in result.output


def test_sibling_entry_edit_does_not_expire_this_entrys_vouch(root: Path) -> None:
    """The defect this replaced: editing entry B expired entry A."""
    two = COMPUTE_ALPHA + (
        "\n### fit-sibling\n\nA second entry sharing the file.\n\n"
        "Output: `results/sibling/fit.json`\n"
    )
    write(root, "specs/compute-alpha.md", two)
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    write(root, "specs/compute-alpha.md", two.replace(
        "A second entry sharing the file.", "Rewritten sibling prose."
    ))
    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "certified" in result.output
    assert "moved since last vouch:" not in result.output


def test_legacy_vouch_without_manifest_still_attributes_coarsely(root: Path) -> None:
    vouch_ok(root, "fit-alpha")  # writes a row without the decomposed fields
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    result = run_cli("check", "--path", str(root))
    assert "moved since vouch: code moved" in result.output  # coarse, not wrong


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


def test_status_leads_with_two_coordinates_not_one_word(root: Path) -> None:
    """§11: a 2D state projected to 1D cannot say an entry is unvouched
    *and* stale, which is the common case while both queues drain."""
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    out = run_cli("status", "fit-alpha", "--path", str(root)).output
    assert "state:" in out and "unvouched · stale" in out
    assert "audit needed" not in out, "the fused word is retired from surfaces"


def test_status_list_shows_both_axes(root: Path) -> None:
    make_ready(root)
    out = run_cli("status", "--path", str(root)).output
    assert "certified · current" in out


def test_downstream_says_which_tree_it_waits_on(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    out = run_cli("status", "fit-beta", "--path", str(root)).output
    assert "waiting on minds and machines" in out
