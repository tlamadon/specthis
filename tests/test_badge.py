"""Badges: the two queues, projected to shields.io endpoint JSON."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from specthis import badge
from specthis.check import check_project
from specthis.cli import main
from specthis.install import WORKFLOW_NAMES, install_workflows
from specthis.parse import load_project, load_project_lenient

from .conftest import fake_run, make_ready, vouch_ok, write

SOURCE_SPEC = """\
---
group: data
---

# Raw wages

### raw-wages

IPUMS extract #14.

- produces: data/raw/wages.parquet
"""


def endpoints(root: Path, no_data: bool = False) -> dict[str, dict]:
    project, problems = load_project_lenient(root)
    return badge.endpoints(project, check_project(project), problems, no_data)


def run_cli(*a: str):
    return CliRunner().invoke(main, list(a))


# ------------------------------------------------------ the projection


def test_a_fresh_project_needs_minds_and_machines(root: Path) -> None:
    b = endpoints(root)
    assert b["mind"] == {
        "schemaVersion": 1,
        "label": "minds",
        "message": "3 waiting",
        "color": badge.AMBER,
    }
    assert b["machine"]["message"] == "3 stale"
    assert b["machine"]["color"] == badge.AMBER


def test_both_go_green_when_the_whole_chain_is_ready(root: Path) -> None:
    make_ready(root)
    b = endpoints(root)
    assert (b["mind"]["message"], b["mind"]["color"]) == ("certified", badge.GREEN)
    assert (b["machine"]["message"], b["machine"]["color"]) == ("current", badge.GREEN)


def test_the_trees_move_independently(root: Path) -> None:
    """A vouched-but-never-run chain: minds done, machines not."""
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)
    b = endpoints(root)
    assert b["mind"]["message"] == "certified"
    assert b["machine"]["message"] == "3 stale"


def test_a_rejection_takes_the_colour_and_its_own_count(root: Path) -> None:
    make_ready(root)
    assert run_cli(
        "vouch", "fit-beta", "--as", "ben", "--reject", "--note", "no", "--path", str(root)
    ).exit_code == 0
    mind = endpoints(root)["mind"]
    assert mind["color"] == badge.RED
    assert mind["message"] == "1 rejected"


def test_rejections_and_pending_judgments_are_counted_apart(root: Path) -> None:
    vouch_ok(root, "fit-alpha")
    fake_run(root, "fit-alpha")
    assert run_cli(
        "vouch", "fit-alpha", "--as", "ben", "--reject", "--path", str(root)
    ).exit_code == 0
    mind = endpoints(root)["mind"]
    assert mind["message"] == "1 rejected, 2 waiting"
    assert mind["color"] == badge.RED


def test_an_unparseable_tree_poisons_both_badges(root: Path) -> None:
    """A lenient load drops what it cannot read; green over that would be
    counting the survivors and calling it the project."""
    write(root, "specs/broken.md", "### \n\n- consumes:\n")
    b = endpoints(root)
    assert [x["color"] for x in b.values()] == [badge.RED, badge.RED]
    assert "spec problem" in b["mind"]["message"]


def test_an_empty_tree_is_grey_not_green(tmp_path: Path) -> None:
    (tmp_path / "specs").mkdir()
    b = endpoints(tmp_path)
    assert [x["message"] for x in b.values()] == ["no entries", "no entries"]
    assert [x["color"] for x in b.values()] == [badge.GREY, badge.GREY]


# ------------------------------------------- the CI-without-data caveat


def test_a_recorded_source_without_its_bytes_is_a_fetch_not_a_break(root: Path) -> None:
    """The whole point of the flag: a CI checkout carries no data, and a
    source is the one entry whose subject *is* the bytes."""
    write(root, "specs/raw-wages.md", SOURCE_SPEC)
    write(root, "data/raw/wages.parquet", "bytes")
    vouch_ok(root, "raw-wages")
    assert run_cli("record", "raw-wages", "--path", str(root)).exit_code == 0
    make_ready(root)
    assert endpoints(root)["mind"]["message"] == "certified"

    (root / "data/raw/wages.parquet").unlink()  # as a bare clone would have it
    assert endpoints(root, no_data=False)["mind"]["message"] == "1 waiting"
    assert endpoints(root, no_data=True)["mind"]["message"] == "certified"
    assert endpoints(root, no_data=True)["machine"]["message"] == "current"


def test_a_source_nobody_ever_recorded_still_counts(root: Path) -> None:
    """--no-data forgives absence, never a dataset that was never placed:
    a ledger row is what says the bytes exist somewhere."""
    write(root, "specs/raw-wages.md", SOURCE_SPEC)
    make_ready(root)
    assert endpoints(root, no_data=True)["mind"]["message"] == "1 waiting"


def test_artifacts_absent_from_a_clone_are_current_not_stale(root: Path) -> None:
    """No flag needed for computed entries — a missing artifact leaves the
    realization current and merely un-materialized."""
    make_ready(root)
    for out in ("results/alpha/fit.json", "results/beta/fit.json", "reports/fig_beta.tex"):
        (root / out).unlink()
    assert endpoints(root)["machine"]["message"] == "current"


def test_the_unfetched_set_is_empty_when_the_bytes_are_there(root: Path) -> None:
    write(root, "specs/raw-wages.md", SOURCE_SPEC)
    write(root, "data/raw/wages.parquet", "bytes")
    project = load_project(root)
    assert badge.unfetched(project, check_project(project)) == set()


# -------------------------------------------------------------- the CLI


def test_badge_prints_both_endpoints_and_always_exits_zero(root: Path) -> None:
    result = run_cli("badge", "--path", str(root))
    assert result.exit_code == 0, result.output  # a full queue is not a failure
    assert set(json.loads(result.output)) == {"mind", "machine"}


def test_badge_out_writes_one_file_per_tree(root: Path) -> None:
    out = root / ".badges"
    assert run_cli("badge", "--out", str(out), "--path", str(root)).exit_code == 0
    body = json.loads((out / "mind.json").read_text())
    assert body["schemaVersion"] == 1 and body["label"] == "minds"
    assert json.loads((out / "machine.json").read_text())["label"] == "machines"


def test_badge_writes_nothing_into_the_ledgers(root: Path) -> None:
    """It is a view: `check` never reads it back, and it never writes."""
    make_ready(root)
    before = {p.name: p.read_bytes() for p in (root / "specs").iterdir() if p.is_file()}
    assert run_cli("badge", "--out", str(root / ".badges"), "--path", str(root)).exit_code == 0
    after = {p.name: p.read_bytes() for p in (root / "specs").iterdir() if p.is_file()}
    assert before == after


def test_markdown_needs_a_repo_it_cannot_guess(root: Path) -> None:
    result = run_cli("badge", "--markdown", "--repo", "acme/widgets", "--path", str(root))
    assert result.exit_code == 0
    assert "raw.githubusercontent.com/acme/widgets/badges/mind.json" in result.output
    assert "machine.json" in result.output


def test_markdown_honours_the_branch(root: Path) -> None:
    result = run_cli(
        "badge", "--markdown", "--repo", "acme/widgets", "--branch", "gh-pages",
        "--path", str(root),
    )
    assert "acme/widgets/gh-pages/mind.json" in result.output


def test_slug_reads_both_remote_forms() -> None:
    assert badge.slug("git@github.com:tlamadon/specthis.git") == "tlamadon/specthis"
    assert badge.slug("https://github.com/tlamadon/specthis.git\n") == "tlamadon/specthis"
    assert badge.slug("https://github.com/tlamadon/specthis") == "tlamadon/specthis"
    assert badge.slug("https://gitlab.com/tlamadon/specthis.git") is None


# --------------------------------------------------------- the workflow


def test_workflows_are_opt_in(tmp_path: Path) -> None:
    assert run_cli("install", "--path", str(tmp_path)).exit_code == 0
    assert not (tmp_path / ".github").exists()


def test_install_workflows_writes_the_badge_job(tmp_path: Path) -> None:
    installed, skipped = install_workflows(project_path=tmp_path)
    assert installed == list(WORKFLOW_NAMES) and skipped == []
    body = (tmp_path / ".github" / "workflows" / "badges.yml").read_text()
    assert "specthis badge --out .badges --no-data" in body
    assert "contents: write" in body
    # idempotent without force
    installed, skipped = install_workflows(project_path=tmp_path)
    assert installed == [] and len(skipped) == len(WORKFLOW_NAMES)


def test_install_workflows_flag(tmp_path: Path) -> None:
    result = run_cli("install", "--workflows", "--path", str(tmp_path))
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".github" / "workflows" / "badges.yml").exists()
    assert "badges.yml" in result.output
