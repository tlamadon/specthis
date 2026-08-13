"""The worked example in `examples/wages`, executed.

A guided walkthrough that is not run is a walkthrough that rots. Every
command in its README appears here, in order, against a copy of the
example — so the documentation cannot drift from the tool.
"""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.check import Certification, Realization, check_project
from specthis.cli import main
from specthis.parse import load_project

EXAMPLE = Path(__file__).parent.parent / "examples" / "wages"


@pytest.fixture
def wages(tmp_path: Path) -> Path:
    root = tmp_path / "wages"
    shutil.copytree(EXAMPLE, root)
    return root


def cli(root: Path, *args: str):
    result = CliRunner().invoke(main, [*args, "--path", str(root)])
    return result


def axes(root: Path, name: str) -> tuple[Certification, Realization | None]:
    r = check_project(load_project(root))[name]
    return r.certification, r.realization


def walk_through(root: Path) -> None:
    """§2–§4 of the README: record, build, vouch."""
    assert cli(root, "record", "raw-wages").exit_code == 0
    assert cli(root, "build").exit_code == 0
    for entry in ("raw-wages", "clean-wages", "wage-moments", "wage-table"):
        assert cli(root, "vouch", entry, "--as", "ana").exit_code == 0


# ------------------------------------------------------------ the walkthrough


def test_the_example_lints_clean(wages: Path) -> None:
    result = cli(wages, "lint")
    assert result.exit_code == 0, result.output
    assert "specs are clean" in result.output


def test_the_source_entry_has_no_code_and_no_step(wages: Path) -> None:
    """It arrived; nobody computed it."""
    from specthis.check import is_source

    project = load_project(wages)
    entry = project.entries["raw-wages"]
    assert is_source(entry)
    assert "raw-wages" not in project.steps


def test_record_then_build_then_vouch_reaches_ready(wages: Path) -> None:
    walk_through(wages)
    result = cli(wages, "check")
    assert result.exit_code == 0, result.output
    assert "ready: 4/4" in result.output


def test_the_table_is_produced(wages: Path) -> None:
    walk_through(wages)
    table = (wages / "reports/table.md").read_text()
    assert "| year | n | mean log wage | variance |" in table
    assert "| 2019 | 4 |" in table
    assert "| 2020 | 3 |" in table, "the negative wage must have been dropped"


def test_building_twice_changes_nothing(wages: Path) -> None:
    walk_through(wages)
    before = (wages / "reports/table.md").read_bytes()
    assert cli(wages, "build").exit_code == 0
    assert (wages / "reports/table.md").read_bytes() == before
    assert "ready: 4/4" in cli(wages, "check").output


# --------------------------------------------------------------- §5, the point


def test_a_prose_edit_moves_only_the_mind_queue(wages: Path) -> None:
    walk_through(wages)
    spec = wages / "specs/wages.md"
    spec.write_text(spec.read_text().replace(
        "Four decimal places.", "Four decimal places. Round half to even."))

    cert, real = axes(wages, "wage-table")
    assert cert is Certification.UNVOUCHED, "the contract changed"
    assert real is Realization.CURRENT, "no bytes moved: a clarification costs zero compute"


def test_a_sibling_entry_in_the_same_file_is_untouched(wages: Path) -> None:
    """A vouch pins the entry's own block, not the whole file."""
    walk_through(wages)
    spec = wages / "specs/wages.md"
    spec.write_text(spec.read_text().replace(
        "Four decimal places.", "Four decimal places. Round half to even."))

    for other in ("raw-wages", "clean-wages", "wage-moments"):
        assert axes(wages, other)[0] is Certification.CERTIFIED


def test_a_code_edit_moves_both_queues(wages: Path) -> None:
    walk_through(wages)
    script = wages / "scripts/moments.py"
    script.write_text(script.read_text().replace("round(m, 4)", "round(m, 5)"))

    cert, real = axes(wages, "wage-moments")
    assert cert is Certification.UNVOUCHED
    assert real is Realization.STALE, "code sits in both claims"


def test_the_two_queues_drain_independently(wages: Path) -> None:
    """The machine can rebuild while a mind is still reading."""
    walk_through(wages)
    script = wages / "scripts/moments.py"
    script.write_text(script.read_text().replace("round(m, 4)", "round(m, 5)"))

    assert cli(wages, "build").exit_code == 0
    cert, real = axes(wages, "wage-moments")
    assert real is Realization.CURRENT, "bytes repaired without a vouch"
    assert cert is Certification.UNVOUCHED, "and the judgment still expired"

    assert cli(wages, "vouch", "wage-moments", "--as", "ana").exit_code == 0
    assert axes(wages, "wage-moments")[0] is Certification.CERTIFIED


# ----------------------------------------------------------- what to try next


def test_a_tampered_product_is_caught_and_force_repairs_it(wages: Path) -> None:
    """A manager keying on inputs cannot see this: its inputs did not move."""
    walk_through(wages)
    (wages / "reports/table.md").write_text("| year | n |\n|---|---|\n| 1999 | 0 |\n")
    assert axes(wages, "wage-table")[1] is Realization.STALE

    assert cli(wages, "build", "wage-table", "--force").exit_code == 0
    assert axes(wages, "wage-table")[1] is Realization.CURRENT


def test_lint_catches_an_edge_the_pipeline_stops_building(wages: Path) -> None:
    pipeline = wages / "pipeline.toml"
    pipeline.write_text(pipeline.read_text().replace(
        'deps    = ["scripts/moments.py", "data/wages.csv"]',
        'deps    = ["scripts/moments.py"]'))
    result = cli(wages, "lint")
    assert result.exit_code == 1
    assert "the contract declares an edge the pipeline does not build" in result.output


# ============================================================== wage-grid

GRID = Path(__file__).parent.parent / "examples" / "wage-grid"
COUNTRIES = ("chile", "argentina")


@pytest.fixture
def grid(tmp_path: Path) -> Path:
    root = tmp_path / "wage-grid"
    shutil.copytree(GRID, root)
    return root


def build_grid(root: Path) -> None:
    for c in COUNTRIES:
        assert cli(root, "record", f"raw-wages[country={c}]").exit_code == 0
    assert cli(root, "build").exit_code == 0


def test_the_grid_lints_clean(grid: Path) -> None:
    result = cli(grid, "lint")
    assert result.exit_code == 0, result.output


def test_instances_come_from_the_pipeline_whatever_the_steps_are_called(grid: Path) -> None:
    """The steps are `clean-chile`, not `clean-wages@chile`: identity is
    matched from the output path, so no naming convention is imposed."""
    from specthis.instances import instances

    project = load_project(grid)
    found = {i.name: i.step for i in instances(project, project.entries["clean-wages"])}
    assert found == {
        "clean-wages[country=chile]": "clean-chile",
        "clean-wages[country=argentina]": "clean-argentina",
    }


def test_four_entries_yield_seven_claims(grid: Path) -> None:
    build_grid(grid)
    reports = check_project(load_project(grid))
    assert len(reports) == 7
    assert "clean-wages" not in reports, "the template itself is not a claim"


def test_the_grid_reaches_ready(grid: Path) -> None:
    build_grid(grid)
    for entry in (*[f"raw-wages[country={c}]" for c in COUNTRIES],
                  "clean-wages", "wage-moments", "wage-comparison"):
        assert cli(grid, "vouch", entry, "--as", "ana").exit_code == 0
    result = cli(grid, "check")
    assert result.exit_code == 0, result.output
    assert "ready: 7/7" in result.output


def test_the_comparison_aggregates_every_country(grid: Path) -> None:
    build_grid(grid)
    table = (grid / "reports/comparison.md").read_text()
    assert "| argentina |" in table and "| chile |" in table


def test_one_vouch_covers_every_instance(grid: Path) -> None:
    build_grid(grid)
    assert cli(grid, "vouch", "clean-wages", "--as", "ana").exit_code == 0
    for c in COUNTRIES:
        assert axes(grid, f"clean-wages[country={c}]")[0] is Certification.CERTIFIED


def test_an_instance_vouch_wins_over_the_template(grid: Path) -> None:
    """Sign the template when the code really is country-agnostic; sign
    instances when it is not. You choose by where you file it."""
    build_grid(grid)
    assert cli(grid, "vouch", "clean-wages[country=chile]", "--as", "ana").exit_code == 0
    assert axes(grid, "clean-wages[country=chile]")[0] is Certification.CERTIFIED
    assert axes(grid, "clean-wages[country=argentina]")[0] is Certification.UNVOUCHED


def test_breaking_one_country_leaves_the_other_alone(grid: Path) -> None:
    build_grid(grid)
    raw = grid / "data/raw/chile/wages.csv"
    raw.write_text(raw.read_text() + "4,2020,55000\n")

    assert axes(grid, "clean-wages[country=chile]")[1] is Realization.STALE
    assert axes(grid, "clean-wages[country=argentina]")[1] is Realization.CURRENT


def test_a_templated_source_is_pinned_per_instance(grid: Path) -> None:
    """Its bytes arrive from outside, so it has no step — each country's
    extract is recorded on its own."""
    from specthis.check import is_source

    project = load_project(grid)
    assert is_source(project.entries["raw-wages"])
    build_grid(grid)
    from specthis.ledger import read_runs

    runs = read_runs(grid / "specs")
    assert {f"raw-wages[country={c}]" for c in COUNTRIES} <= set(runs)
