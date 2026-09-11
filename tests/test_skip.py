"""skip: true (dormant but checked) and draft: true (unchecked prose)."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.check import Status, check_project
from specthis.cli import main
from specthis.export import render
from specthis.parse import SpecError, draft_warnings, load_project_lenient, parse_spec

from .conftest import COMPUTE_ALPHA, COMPUTE_BETA, REPORT_BETA, make_ready, write
from .test_library import ESTIMATORS, add_library, ready_all


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def skip_alpha(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\nskip: true"
    ))


def draft_alpha(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\ndraft: true"
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


def test_skipped_body_is_grammar_checked(root: Path) -> None:
    # a dormant contract is still a contract: no Output: is a problem
    write(root, "specs/wip.md", "---\nname: wip\nkind: compute\nskip: true\n---\n\n"
          "# wip\n\n## Entry\n\n### half-written\n\nNo output yet.\n")
    _, problems = load_project_lenient(root)
    assert any("declares no `Output:` path" in p.message for p in problems)


def test_skipped_library_binding_stays_best_effort(root: Path) -> None:
    # grammar and edges are what skip keeps; the map is checked when the
    # entry wakes, so an unbound dormant library module stays clean
    write(root, "specs/estimators.md", ESTIMATORS.replace(
        "kind: library", "kind: library\nskip: true"
    ))
    project, problems = load_project_lenient(root)
    assert problems == []
    assert "estimator-core" in project.skipped_entries


def test_draft_body_is_not_grammar_checked(root: Path) -> None:
    write(root, "specs/wip.md", "---\nname: wip\nkind: compute\ndraft: true\n---\n\n"
          "# wip\n\n## Entry\n\n### half-written\n\nNo output yet.\n")
    project, problems = load_project_lenient(root)
    assert problems == []
    assert "half-written" in project.skipped_entries
    assert "half-written" in project.draft_entries


def test_draft_bypasses_field_and_name_checks(root: Path) -> None:
    # bad heading, unknown field key: prose under draft, problems under skip
    body = ("---\nname: wip\nkind: compute\n{flag}: true\n---\n\n"
            "# wip\n\n## Entry\n\n### Bad Name!\n\n- bogus_key: x\n")
    write(root, "specs/wip.md", body.format(flag="draft"))
    project, problems = load_project_lenient(root)
    assert problems == []
    assert "Bad Name!" in project.draft_entries

    write(root, "specs/wip.md", body.format(flag="skip"))
    _, problems = load_project_lenient(root)
    assert any("bad entry name" in p.message for p in problems)


def test_draft_implies_skip(root: Path) -> None:
    draft_alpha(root)
    spec = parse_spec(root / "specs/compute-alpha.md")
    assert spec.skip and spec.draft
    project, _ = load_project_lenient(root)
    assert "fit-alpha" not in project.entries
    assert project.skipped_entries["fit-alpha"] == "compute-alpha.md"
    assert project.draft_entries["fit-alpha"] == "compute-alpha.md"


def test_skip_must_be_boolean(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\nskip: yes please"
    ))
    with pytest.raises(SpecError, match="must be true or false"):
        parse_spec(root / "specs/compute-alpha.md")


def test_draft_must_be_boolean(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\ndraft: soon"
    ))
    with pytest.raises(SpecError, match="must be true or false"):
        parse_spec(root / "specs/compute-alpha.md")


# ---------------------------------------------------------------- names


def test_skipped_entries_share_the_live_namespace(root: Path) -> None:
    skip_alpha(root)
    write(root, "specs/rival.md", "---\nname: rival\nkind: compute\n---\n\n"
          "# rival\n\n## Entry\n\n### fit-alpha\n\nMine now.\n\n"
          "Output: `results/rival/fit.json`\n")
    _, problems = load_project_lenient(root)
    assert any("duplicate entry name `fit-alpha`" in p.message for p in problems)


def test_two_skipped_specs_cannot_claim_one_name(root: Path) -> None:
    tmpl = ("---\nname: {n}\nkind: compute\nskip: true\n---\n\n"
            "# {n}\n\n## Entry\n\n### shared-claim\n\nText.\n\n"
            "Output: `results/{n}/out.json`\n")
    write(root, "specs/wip-a.md", tmpl.format(n="wip-a"))
    write(root, "specs/wip-b.md", tmpl.format(n="wip-b"))
    _, problems = load_project_lenient(root)
    assert any("duplicate entry name `shared-claim`" in p.message for p in problems)


def test_draft_names_never_shadow_or_collide(root: Path) -> None:
    # a draft heading is prose: it claims nothing, so a name collision
    # with a live entry is not a problem and the live entry stays whole
    write(root, "specs/wip.md", "---\nname: wip\nkind: compute\ndraft: true\n---\n\n"
          "# wip\n\n## Entry\n\n### fit-alpha\n\nRewrite, one day.\n")
    project, problems = load_project_lenient(root)
    assert problems == []
    assert project.entries["fit-alpha"].spec.name == "compute-alpha"
    assert "fit-alpha" not in project.draft_entries


# ---------------------------------------------------------------- edges


def test_dormant_edges_between_skipped_specs_are_fine(root: Path) -> None:
    for name, text in (("compute-alpha", COMPUTE_ALPHA), ("compute-beta", COMPUTE_BETA),
                       ("report-beta", REPORT_BETA)):
        kind = text.splitlines()[2]
        write(root, f"specs/{name}.md", text.replace(kind, f"{kind}\nskip: true"))
    _, problems = load_project_lenient(root)
    assert problems == []


def test_skipped_spec_consuming_unknown_entry_is_a_problem(root: Path) -> None:
    write(root, "specs/compute-beta.md", COMPUTE_BETA.replace(
        "kind: compute", "kind: compute\nskip: true"
    ).replace("fit-alpha", "no-such-entry"))
    _, problems = load_project_lenient(root)
    assert any("consumes unknown entry `no-such-entry`" in p.message for p in problems)


def test_skipped_spec_references_are_validated(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace(
        "kind: compute", "kind: compute\nskip: true"
    ).replace("models.md", "nowhere.md"))
    _, problems = load_project_lenient(root)
    assert any("references unknown spec `nowhere.md`" in p.message for p in problems)


def test_live_spec_consuming_a_draft_entry_is_a_problem(root: Path) -> None:
    draft_alpha(root)
    _, problems = load_project_lenient(root)
    assert any(
        "consumes draft entry `fit-alpha`" in p.message and "draft: true" in p.message
        for p in problems
    )


def test_lint_surfaces_drafts(root: Path) -> None:
    draft_alpha(root)
    write(root, "specs/compute-beta.md", COMPUTE_BETA.replace(
        "kind: compute", "kind: compute\nskip: true"
    ))
    write(root, "specs/models.md", "---\nname: models\nkind: definitions\ndraft: true\n---\n\n"
          "# models\n\nVocabulary only.\n")
    write(root, "specs/report-beta.md", REPORT_BETA.replace(
        "consumes:", "references:\n  - models.md\nconsumes:"
    ))
    project, _ = load_project_lenient(root)
    warnings = [w.message for w in draft_warnings(project)]
    assert any("compute-alpha.md is draft" in w for w in warnings)
    assert any("compute-beta.md: consumes draft entry `fit-alpha`" in w for w in warnings)
    assert any("references draft spec `models.md`" in w for w in warnings)

    result = run_cli("lint", "--path", str(root))
    assert "compute-alpha.md is draft" in result.output


# ---------------------------------------------------------------- verbs


def test_check_excludes_skipped_from_all_counts(root: Path) -> None:
    make_ready(root)
    write(root, "specs/report-beta.md", REPORT_BETA.replace(
        "kind: report", "kind: report\nskip: true"
    ))
    result = run_cli("check", "--path", str(root))
    assert "fig-beta" not in result.output  # not itemized anywhere
    assert "ready: 2/2 (+1 skipped)" in result.output


def test_check_counts_drafts_inside_skipped(root: Path) -> None:
    make_ready(root)
    write(root, "specs/report-beta.md", REPORT_BETA.replace(
        "kind: report", "kind: report\ndraft: true"
    ))
    result = run_cli("check", "--path", str(root))
    assert "ready: 2/2 (+1 skipped, 1 draft)" in result.output


def test_record_vouch_status_refuse_skipped(root: Path) -> None:
    skip_alpha(root)
    for verb in (("record", "fit-alpha"), ("vouch", "fit-alpha", "--as", "ana"),
                 ("status", "fit-alpha")):
        result = run_cli(*verb, "--path", str(root))
        assert result.exit_code != 0
        assert "skip: true" in result.output
        assert "compute-alpha.md" in result.output


def test_record_vouch_status_refuse_draft(root: Path) -> None:
    draft_alpha(root)
    for verb in (("record", "fit-alpha"), ("vouch", "fit-alpha", "--as", "ana"),
                 ("status", "fit-alpha")):
        result = run_cli(*verb, "--path", str(root))
        assert result.exit_code != 0
        assert "draft: true" in result.output
        assert "unchecked prose" in result.output


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


# ----------------------------------------------------------------- view


def test_viewer_renders_skipped_greyed_not_gone(root: Path) -> None:
    make_ready(root)
    skip_alpha(root)
    project, problems = load_project_lenient(root)
    page, index = render(project, problems)

    assert '<section class="spec skipped" id="spec-compute-alpha">' in page
    assert "skipped — entries dormant" in page  # spec-meta badge
    assert '<span class="badge skipped">skipped</span>' in page  # entry row
    assert "Fit the alpha model" in page  # markdown still rendered
    assert '<span class="chip"><b>1</b> skipped</span>' in page  # status chips
    assert '"skip": true' not in page  # (index is JSON, page is HTML)

    by_name = {s["name"]: s for s in index["specs"]}
    assert by_name["compute-alpha"]["skip"] is True
    assert by_name["compute-alpha"]["entries"][0]["status"] == "skipped"


def test_viewer_renders_draft_badge(root: Path) -> None:
    make_ready(root)
    draft_alpha(root)
    project, problems = load_project_lenient(root)
    page, index = render(project, problems)

    assert "draft — unchecked prose" in page  # spec-meta badge
    assert '<span class="badge draft">draft</span>' in page  # entry row
    assert '<span class="chip"><b>1</b> draft</span>' in page  # status chips

    by_name = {s["name"]: s for s in index["specs"]}
    assert by_name["compute-alpha"]["draft"] is True
    assert by_name["compute-alpha"]["entries"][0]["status"] == "draft"
