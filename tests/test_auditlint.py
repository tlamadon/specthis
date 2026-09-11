"""Mechanical spec-text checks: state leaks, dangling pointers, scope creep."""

from pathlib import Path

from click.testing import CliRunner

from specthis.auditlint import spec_text_problems, spec_text_warnings
from specthis.cli import main
from specthis.parse import load_project_lenient

from .conftest import COMPUTE_ALPHA, COMPUTE_BETA, REPORT_BETA, write


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def _audit(root: Path):
    project, _ = load_project_lenient(root)
    return spec_text_problems(project), spec_text_warnings(project)


def test_the_fixture_is_clean(root: Path) -> None:
    problems, warnings = _audit(root)
    assert problems == []
    assert warnings == []


# ------------------------------------------------------- state leaks


def test_a_state_leak_is_a_problem(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + "\nStatus: done\n")
    problems, _ = _audit(root)
    assert any("`Status:` is project state" in p.message for p in problems)

    result = run_cli("lint", "--path", str(root))
    assert result.exit_code == 1
    assert "project state in a spec body" in result.output


def test_fenced_or_backticked_mentions_are_not_leaks(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + (
        "\nNever write a `Status:` line.\n\n```\nScript: example.py\n```\n"
    ))
    problems, _ = _audit(root)
    assert problems == []


def test_state_leaks_reach_check_json(root: Path) -> None:
    # the yolo Stop hook blocks on lint.problems — a leak must hold it
    import json

    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + "\nScript: scripts/x.py\n")
    result = run_cli("check", "--json", "--path", str(root))
    state = json.loads(result.output)
    assert state["lint"]["problems"] == 1
    assert result.exit_code == 1


def test_warnings_do_not_reach_check_json(root: Path) -> None:
    # advice must never trap a session: warning-tier findings stay out
    import json

    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "per models.md", "per the model definitions"
    ))
    _, warnings = _audit(root)
    assert warnings  # the reference is now unmentioned
    result = run_cli("check", "--json", "--path", str(root))
    state = json.loads(result.output)
    assert state["lint"]["problems"] == 0


# ---------------------------------------------------- dangling pointers


def test_an_unmentioned_reference_warns(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "per models.md", "per the model definitions"
    ))
    _, warnings = _audit(root)
    assert any("references `models.md` but the body never mentions it" in w.message
               for w in warnings)


def test_a_dangling_spec_link_warns(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + "\nSee [notes](old-notes.md).\n")
    _, warnings = _audit(root)
    assert any("link to `old-notes.md` resolves to nothing" in w.message for w in warnings)


def test_known_links_are_quiet(root: Path) -> None:
    write(root, "journal/2026-01-02-note.md", "# note\n\nA journal entry.\n")
    write(root, "specs/design.md", "A sibling non-spec file.\n")
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + (
        "\nSee [models](models.md), [the note](journal/2026-01-02-note.md),\n"
        "[design](design.md), and [the site](https://example.org/x.md).\n"
    ))
    _, warnings = _audit(root)
    assert warnings == []


# --------------------------------------------------- dangling mentions


def test_a_path_mention_nothing_backs_warns(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + (
        "\nReads the raw pull from `data/raw/wages_v2.parquet`.\n"
    ))
    _, warnings = _audit(root)
    assert any("mentions `data/raw/wages_v2.parquet` — nothing produces it" in w.message
               for w in warnings)


def test_backed_path_mentions_are_quiet(root: Path) -> None:
    write(root, "data/raw/pull.csv", "a,b\n")
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + (
        "\nDeclared output: `results/alpha/fit.json` (not yet built).\n"      # an output
        "Implemented in `scripts/fit_alpha.py`.\n"                            # a bound script
        "Raw bytes land at `data/raw/pull.csv`.\n"                            # on disk
        "Run `uv run scripts/fit_alpha.py --fast` yourself.\n"                # a command, not a path
        "The manager fills `{out}` and matches `src/pkg/**/*.py`.\n"          # placeholder, glob
    ))
    _, warnings = _audit(root)
    assert warnings == []


def test_a_near_miss_entry_name_warns_with_a_suggestion(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + (
        "\nDownstream, `fit-betas` consumes this fit.\n"
    ))
    _, warnings = _audit(root)
    assert any("no such entry; did you mean `fit-beta`?" in w.message for w in warnings)


def test_known_and_unrelated_slugs_are_quiet(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + (
        "\nExact names are fine: `fit-beta`. So is tool vocabulary:\n"
        "`spec-critic` judges this entry. A slug close to nothing —\n"
        "`read-modify-write` — is a concept, not a typo; the reader's job.\n"
    ))
    _, warnings = _audit(root)
    assert warnings == []


def test_dormant_entry_mentions_are_wired_not_dangling(root: Path) -> None:
    write(root, "specs/compute-beta.md", COMPUTE_BETA.replace(
        "kind: compute", "kind: compute\nskip: true"
    ))
    write(root, "specs/report-beta.md", REPORT_BETA.replace(
        "kind: report", "kind: report\nskip: true"
    ))
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + (
        "\nThe dormant `fit-beta` will read `results/beta/fit.json` when it wakes.\n"
    ))
    _, warnings = _audit(root)
    assert not any("mentions" in w.message for w in warnings)


def test_meta_and_definitions_prose_is_not_scanned_for_mentions(root: Path) -> None:
    # a spec with no entries documents; its example paths are not claims
    write(root, "specs/models.md", "---\nname: models\nkind: definitions\n---\n\n"
          "# models\n\nExamples live at `results/examples/demo.json`.\n")
    _, warnings = _audit(root)
    assert warnings == []


# -------------------------------------------------------- scope creep


def test_compute_output_under_reports_warns(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "results/alpha/fit.json", "reports/alpha_table.tex"
    ))
    _, warnings = _audit(root)
    assert any("outputs `reports/alpha_table.tex`" in w.message for w in warnings)


def test_a_report_spec_without_artefact_design_warns(root: Path) -> None:
    write(root, "specs/report-beta.md", REPORT_BETA.replace(
        "## Artefact design\n\nOne scatter, journal palette, caption states the sample.\n\n",
        "",
    ))
    _, warnings = _audit(root)
    assert any("no `## Artefact design` section" in w.message for w in warnings)


# --------------------------------------------------------------- scope


def test_skipped_specs_are_scanned(root: Path) -> None:
    # dormant text is still contract text — that is the point of the split
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\nskip: true"
    ) + "\nStatus: done\n")
    problems, _ = _audit(root)
    assert any("`Status:` is project state" in p.message for p in problems)


def test_draft_specs_are_not_scanned(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\ndraft: true"
    ) + "\nStatus: done\n")
    problems, warnings = _audit(root)
    assert problems == []
    assert not any("compute-alpha" in w.message for w in warnings)
