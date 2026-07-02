"""Lenient loading, `specthis lint`, and problem surfacing in views."""

from pathlib import Path

from click.testing import CliRunner

from specthis.check import Status, check_project
from specthis.cli import main
from specthis.export import render
from specthis.parse import load_project_lenient

from .conftest import COMPUTE_ALPHA, make_ready, write
from .test_library import ESTIMATORS, add_library


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def test_lenient_load_collects_all_problems(root: Path) -> None:
    write(root, "specs/compute-alpha.md", "# no frontmatter\n")  # unparseable
    write(root, "specs/estimators.md", ESTIMATORS)  # library, unbound
    project, problems = load_project_lenient(root)

    messages = "\n".join(p.message for p in problems)
    assert "missing YAML frontmatter" in messages
    assert "needs `scripts` in specs/bindings.toml" in messages
    # compute-beta consumes fit-alpha, whose spec no longer parses
    assert "consumes unknown entry `fit-alpha`" in messages
    assert len(problems) == 3

    # the parseable part of the tree still stands
    assert "fit-beta" in project.entries and "fig-beta" in project.entries
    assert "fit-alpha" not in project.entries
    # the unbound library entry degrades to unimplemented, not a crash
    assert check_project(project)["estimator-core"].status is Status.UNIMPLEMENTED


def test_lint_lists_everything_and_exits_nonzero(root: Path) -> None:
    write(root, "specs/estimators.md", ESTIMATORS)  # unbound library entry
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("kind: compute", "kind: banana"))
    result = run_cli("lint", "--path", str(root))
    assert result.exit_code == 1
    assert "needs `scripts`" in result.output
    assert "not one of" in result.output  # independent problems in ONE pass
    # breaking compute-alpha also orphans compute-beta's consumes edge
    assert "consumes unknown entry `fit-alpha`" in result.output
    assert "3 problem(s)" in result.output


def test_lint_clean(root: Path) -> None:
    result = run_cli("lint", "--path", str(root))
    assert result.exit_code == 0
    assert "specs are clean" in result.output


def test_check_survives_grammar_problems(root: Path) -> None:
    make_ready(root)
    write(root, "specs/estimators.md", ESTIMATORS)  # unbound library entry
    result = run_cli("check", "--path", str(root))
    assert result.exit_code == 1  # problems force a non-zero exit...
    assert "spec problems" in result.output
    # ...but the parseable entries still get their statuses derived
    assert "unimplemented" in result.output  # the unbound library entry
    assert "ready: 3/4" in result.output


def test_viewer_renders_around_broken_files(root: Path) -> None:
    make_ready(root)
    write(root, "specs/compute-alpha.md", "# broken but interesting prose\n")
    project, problems = load_project_lenient(root)
    page, _, _ = render(project, problems)

    assert "Spec problems" in page  # status-section box
    assert "does not parse" in page  # sidebar group for the broken file
    assert 'id="spec-compute-alpha"' in page  # broken file gets a section...
    assert "broken but interesting prose" in page  # ...with best-effort markdown
    assert 'id="spec-compute-beta"' in page  # healthy specs render as usual
    assert "fit-beta" in page


def test_export_writes_despite_problems(root: Path) -> None:
    write(root, "specs/compute-alpha.md", "# no frontmatter\n")
    result = run_cli("export", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "Spec problems" in (root / "specs/specs.html").read_text()


def test_run_and_vouch_stay_strict(root: Path) -> None:
    write(root, "specs/estimators.md", ESTIMATORS)  # unbound library entry
    for verb in (("run", "fit-alpha"), ("vouch", "fit-alpha", "--as", "ana")):
        result = run_cli(*verb, "--path", str(root))
        assert result.exit_code != 0
        assert "needs `scripts`" in result.output


def test_strict_error_aggregates_all_problems(root: Path) -> None:
    import pytest

    from specthis.parse import SpecError, load_project

    write(root, "specs/compute-alpha.md", "# no frontmatter\n")
    write(root, "specs/estimators.md", ESTIMATORS)
    with pytest.raises(SpecError) as exc:
        load_project(root)
    assert "missing YAML frontmatter" in str(exc.value)
    assert "needs `scripts`" in str(exc.value)


def test_library_fixture_still_clean(root: Path) -> None:
    add_library(root)  # properly bound: no problems
    _, problems = load_project_lenient(root)
    assert problems == []
