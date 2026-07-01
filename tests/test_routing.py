from pathlib import Path

from click.testing import CliRunner

from specthis.cli import main
from specthis.export import render
from specthis.parse import load_project
from specthis.routing import build_routing_json, check_routing, scan_host_doc

from .conftest import PAPER_TEX, make_ready, write


def reports(root: Path):
    return {r.spec: r for r in check_routing(load_project(root))}


def test_routed_ok(root: Path) -> None:
    rr = reports(root)["report-beta"]
    assert rr.host_doc_exists and rr.label_found
    assert rr.routed == {"reports/fig_beta.tex": True}  # .dat is exempt (not host-doc input)
    assert rr.extra_inputs == []
    assert rr.ok


def test_orphaned_export(root: Path) -> None:
    write(root, "reports/paper.tex", PAPER_TEX.replace("\\input{fig_beta.tex}\n", ""))
    rr = reports(root)["report-beta"]
    assert rr.orphaned == ["reports/fig_beta.tex"]
    assert not rr.ok


def test_missing_label_and_missing_doc(root: Path) -> None:
    write(root, "reports/paper.tex", PAPER_TEX.replace("sec:beta", "sec:renamed"))
    rr = reports(root)["report-beta"]
    assert rr.host_doc_exists and not rr.label_found

    (root / "reports/paper.tex").unlink()
    rr = reports(root)["report-beta"]
    assert not rr.host_doc_exists


def test_stale_routing_reported_as_extra_inputs(root: Path) -> None:
    write(
        root,
        "reports/paper.tex",
        PAPER_TEX.replace("\\input{fig_beta.tex}", "\\input{fig_beta.tex}\n\\input{ghost.tex}"),
    )
    rr = reports(root)["report-beta"]
    assert rr.extra_inputs == ["ghost.tex"]
    assert rr.ok  # informational, not a failure


def test_comments_are_ignored(root: Path) -> None:
    sections = scan_host_doc(root / "reports/paper.tex")
    assert set(sections) == {"sec:beta", "sec:discussion"}
    assert sections["sec:beta"].inputs == ["fig_beta.tex"]  # commented input not counted


def test_check_prints_warning_but_exit_code_is_claims_only(root: Path) -> None:
    make_ready(root)
    write(root, "reports/paper.tex", PAPER_TEX.replace("\\input{fig_beta.tex}\n", ""))
    result = CliRunner().invoke(main, ["check", "--path", str(root)])
    assert result.exit_code == 0  # all claims hold; routing is a view concern
    assert "never input by reports/paper.tex" in result.output


def test_dashboard_shows_routing(root: Path) -> None:
    make_ready(root)
    page, _, routing_json = render(load_project(root))
    assert "fig_beta.tex" in page and "&#10003;" in page  # routed check mark

    assert routing_json["host_docs"]["reports/paper.tex"]["exists"]
    section = routing_json["host_docs"]["reports/paper.tex"]["sections"]["sec:beta"]
    assert section["inputs"] == ["fig_beta.tex"]

    write(root, "reports/paper.tex", PAPER_TEX.replace("\\input{fig_beta.tex}\n", ""))
    page, _, _ = render(load_project(root))
    assert "orphaned" in page


def test_routing_json_written_by_export(root: Path) -> None:
    result = CliRunner().invoke(main, ["export", "--path", str(root)])
    assert result.exit_code == 0, result.output
    assert (root / "specs/_routing.json").exists()
    assert build_routing_json(load_project(root))["host_docs"]