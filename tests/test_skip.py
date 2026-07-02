"""skip: true — commenting a spec out while developing."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.check import Status, check_project
from specthis.cli import main
from specthis.export import render
from specthis.parse import SpecError, load_project_lenient, parse_spec
from specthis.routing import check_routing

from .conftest import COMPUTE_ALPHA, PAPER_TEX, REPORT_BETA, make_ready, write
from .test_library import ESTIMATORS, add_library, ready_all


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def skip_alpha(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\nskip: true"
    ))


# ---------------------------------------------------------------- parse


def test_skipped_entries_leave_the_dag(root: Path) -> None:
    skip_alpha(root)
    project, problems = load_project_lenient(root)
    assert "fit-alpha" not in project.entries
    assert project.skipped_entries == {"fit-alpha": "compute-alpha.md"}
    # the consumer now has a problem naming the skip, and the edge is gone
    assert any("consumes skipped entry `fit-alpha`" in p.message for p in problems)
    assert "fit-alpha" not in project.entries["fit-beta"].consumes


def test_skipped_body_is_not_grammar_checked(root: Path) -> None:
    # no Output:, unbound library entry — both fine under skip
    write(root, "specs/wip.md", "---\nname: wip\nkind: compute\nskip: true\n---\n\n"
          "# wip\n\n## Entry\n\n### half-written\n\nNo output yet.\n")
    write(root, "specs/estimators.md", ESTIMATORS.replace(
        "kind: library", "kind: library\nskip: true"
    ))
    project, problems = load_project_lenient(root)
    assert problems == []
    assert "half-written" in project.skipped_entries
    assert "estimator-core" in project.skipped_entries


def test_skip_must_be_boolean(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\nskip: yes please"
    ))
    with pytest.raises(SpecError, match="must be true or false"):
        parse_spec(root / "specs/compute-alpha.md")


# ---------------------------------------------------------------- verbs


def test_check_excludes_skipped_from_all_counts(root: Path) -> None:
    make_ready(root)
    write(root, "specs/report-beta.md", REPORT_BETA.replace(
        "kind: report", "kind: report\nskip: true"
    ))
    result = run_cli("check", "--path", str(root))
    assert "fig-beta" not in result.output  # not itemized anywhere
    assert "ready: 2/2 (+1 skipped)" in result.output


def test_run_vouch_status_refuse_skipped(root: Path) -> None:
    skip_alpha(root)
    for verb in (("run", "fit-alpha"), ("vouch", "fit-alpha", "--as", "ana"),
                 ("status", "fit-alpha")):
        result = run_cli(*verb, "--path", str(root))
        assert result.exit_code != 0
        assert "skip: true" in result.output
        assert "compute-alpha.md" in result.output


def test_unskip_honesty(root: Path) -> None:
    make_ready(root)
    skip_alpha(root)
    assert "fit-alpha" not in check_project(load_project_lenient(root)[0])

    # edited while skipped (the usual reason for skipping) -> re-judge
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + "\nTighter contract.\n")
    reports = check_project(load_project_lenient(root)[0])
    assert reports["fit-alpha"].status is Status.AUDIT_NEEDED

    # pure toggle round-trip restores the exact vouched bytes -> trust returns
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA)
    reports = check_project(load_project_lenient(root)[0])
    assert reports["fit-alpha"].status is Status.READY


def test_skipped_library_keeps_blob_carveout(root: Path) -> None:
    add_library(root)
    ready_all(root)
    write(root, "specs/estimators.md", ESTIMATORS.replace(
        "kind: library", "kind: library\nskip: true"
    ))
    project, problems = load_project_lenient(root)
    # non-consumers keep their vouch: the module stays out of the blob
    assert check_project(project)["fit-alpha"].status is Status.READY
    assert "src/pkg/estimator.py" in project.library_scripts
    # the consumer is flagged, not silently trusted
    assert any("consumes skipped entry `estimator-core`" in p.message for p in problems)


def test_routing_exempts_skipped_specs(root: Path) -> None:
    write(root, "reports/paper.tex", PAPER_TEX.replace("\\input{fig_beta.tex}\n", ""))
    assert check_routing(load_project_lenient(root)[0])[0].orphaned  # baseline: warned
    write(root, "specs/report-beta.md", REPORT_BETA.replace(
        "kind: report", "kind: report\nskip: true"
    ))
    assert check_routing(load_project_lenient(root)[0]) == []  # dormant: silent


# ----------------------------------------------------------------- view


def test_viewer_renders_skipped_greyed_not_gone(root: Path) -> None:
    make_ready(root)
    skip_alpha(root)
    project, problems = load_project_lenient(root)
    page, index, _ = render(project, problems)

    assert '<section class="spec skipped" id="spec-compute-alpha">' in page
    assert "skipped — entries dormant" in page  # spec-meta badge
    assert '<span class="badge skipped">skipped</span>' in page  # entry row
    assert "Fit the alpha model" in page  # markdown still rendered
    assert '<span class="chip"><b>1</b> skipped</span>' in page  # status chips
    assert '"skip": true' not in page  # (index is JSON, page is HTML)

    by_name = {s["name"]: s for s in index["specs"]}
    assert by_name["compute-alpha"]["skip"] is True
    assert by_name["compute-alpha"]["entries"][0]["status"] == "skipped"
