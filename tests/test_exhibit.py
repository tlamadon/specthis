"""Exhibits: the manuscript as a terminal node (§2, §5.8, issue #2).

An exhibit is a result a document prints. It produces nothing, has no
code and no step, and its vouch attests that the document describes the
result as the entries it consumes define it — pinning the span it
appears at (``doc:<document>#<label>``) and each consumed contract.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis import hashing
from specthis.check import Certification, check_project, code_manifest, tally
from specthis.cli import main
from specthis.correspond import correspondence_problems
from specthis.ledger import read_vouches
from specthis.parse import Appearance, load_project, load_project_lenient
from specthis.spans import (
    document_problems,
    document_warnings,
    normalize,
    resolve,
    span_sha,
)

from .conftest import make_ready, write

PAPER = r"""\documentclass{article}
\begin{document}

\section{Results}\label{sec:results}

Opening prose, outside every span.

\begin{table}[t]
  \centering
  \caption{Alpha fit}\label{tab:alpha}
  \input{tables/alpha.tex}
  \footnotesize Notes: the loss is recorded at convergence.
\end{table}

\begin{theorem}\label{thm:beta}
  Beta refits on top of the alpha fit.
\end{theorem}

\begin{figure}
  \caption{A schematic}\label{fig:flow}
\end{figure}

\end{document}
"""

EXHIBITS = """\
---
title: The paper
---

# The paper

### tab-alpha

Table 1 prints the alpha fit's loss, as `fit-alpha` defines it.

- consumes: fit-alpha
- appears: paper#tab:alpha

### thm-beta

Theorem 1 states the beta refit `fit-beta` performs.

- consumes: fit-beta
- appears: paper#thm:beta
"""

DOCUMENTS = """
[documents.paper]
path         = "paper/paper.tex"
environments = ["table", "theorem"]
"""


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


@pytest.fixture
def paper(root: Path) -> Path:
    write(root, "paper/paper.tex", PAPER)
    write(root, "specs/paper.md", EXHIBITS)
    bindings = root / "specs/bindings.toml"
    bindings.write_text(bindings.read_text() + DOCUMENTS)
    return root


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text()
    assert old in text, f"{old!r} not in {rel}"
    path.write_text(text.replace(old, new))


def vouch(root: Path, entry: str, *extra: str) -> None:
    result = run_cli("vouch", entry, "--as", "ben", "--path", str(root), *extra)
    assert result.exit_code == 0, result.output


def cert(root: Path, entry: str) -> Certification:
    return check_project(load_project(root))[entry].certification


# ------------------------------------------------------------------ type


def test_an_entry_with_appears_and_no_produces_is_an_exhibit(paper: Path) -> None:
    project = load_project(paper)
    e = project.entries["tab-alpha"]
    assert e.kind == "exhibit"
    assert e.appears == [Appearance("paper", "tab:alpha")]
    assert e.outputs == [] and e.binding.scripts == []


@pytest.mark.parametrize(
    ("field", "says"),
    [
        ("- produces: other-thing", "declares both `appears` and `produces`"),
        ("- code", "has no code"),
        ("- props: country", "cannot be a template"),
    ],
)
def test_contradictory_combinations_name_the_conflict(paper: Path, field: str, says: str) -> None:
    edit(paper, "specs/paper.md", "- appears: paper#tab:alpha", f"- appears: paper#tab:alpha\n{field}")
    _, problems = load_project_lenient(paper)
    assert any(says in p.message for p in problems), [p.message for p in problems]


def test_a_field_list_matching_no_type_names_the_missing_ingredient(paper: Path) -> None:
    edit(paper, "specs/paper.md", "- appears: paper#tab:alpha\n", "")
    _, problems = load_project_lenient(paper)
    message = next(p.message for p in problems if "tab-alpha" in p.message)
    assert "no `- produces:`" in message and "no `- appears:`" in message


def test_appears_must_address_a_span(paper: Path) -> None:
    edit(paper, "specs/paper.md", "paper#tab:alpha", "paper")
    _, problems = load_project_lenient(paper)
    assert any("`<document>#<label>`" in p.message for p in problems)


def test_an_undeclared_document_is_a_problem_that_names_the_fix(paper: Path) -> None:
    edit(paper, "specs/paper.md", "paper#tab:alpha", "paper/paper.tex#tab:alpha")
    project, problems = load_project_lenient(paper)
    message = next(p.message for p in problems if "undeclared document" in p.message)
    assert "names a document, not a path" in message
    assert project.entries["tab-alpha"].appears == []
    assert check_project(project)["tab-alpha"].certification is Certification.UNIMPLEMENTED


def test_an_exhibit_is_terminal_nothing_may_consume_it(paper: Path) -> None:
    edit(paper, "specs/paper.md", "- consumes: fit-beta", "- consumes: fit-beta, tab-alpha")
    project, problems = load_project_lenient(paper)
    assert any("consumes exhibit `tab-alpha`" in p.message for p in problems)
    assert project.entries["thm-beta"].consumes == ["fit-beta"]


def test_an_exhibit_binds_no_code(paper: Path) -> None:
    bindings = paper / "specs/bindings.toml"
    bindings.write_text(bindings.read_text() + '\n[entries.tab-alpha]\nscripts = ["x.py"]\n')
    _, problems = load_project_lenient(paper)
    assert any("is an exhibit — it has no code" in p.message for p in problems)


def test_an_exhibit_has_no_pipeline_step(paper: Path) -> None:
    write(paper, "pipeline.toml", '[steps.tab-alpha]\ncommand = "true"\nouts = ["x"]\n')
    problems = [p.message for p in correspondence_problems(load_project(paper))]
    assert any("`tab-alpha` is an exhibit entry and must have no step" in m for m in problems)


# ----------------------------------------------------------------- spans


def test_a_label_addresses_its_innermost_environment(paper: Path) -> None:
    site = resolve(load_project(paper), Appearance("paper", "thm:beta")).site
    assert site is not None and site.env == "theorem"
    assert site.lines == (15, 17)


def test_an_alignment_wrapper_is_never_the_span(paper: Path) -> None:
    """A label inside `center` names the float around it — pinning only
    the wrapper would leave the table note outside the claim."""
    edit(paper, "paper/paper.tex", "  \\centering\n", "  \\begin{center}\n")
    edit(paper, "paper/paper.tex", "  \\input{tables/alpha.tex}\n", "  \\input{tables/alpha.tex}\n\\end{center}\n")
    site = resolve(load_project(paper), Appearance("paper", "tab:alpha")).site
    assert site is not None and site.env == "table"


def test_a_label_in_no_environment_must_be_marked(paper: Path) -> None:
    edit(paper, "specs/paper.md", "paper#thm:beta", "paper#sec:results")
    project = load_project(paper)
    assert check_project(project)["thm-beta"].certification is Certification.UNIMPLEMENTED
    assert any("sits in no environment" in p.message for p in document_problems(project))


def test_a_marker_pair_addresses_prose_and_overrides_the_environment(paper: Path) -> None:
    edit(paper, "paper/paper.tex", "Opening prose, outside every span.",
         "% specthis:begin{sec:results}\nOpening prose, now pinned.\n% specthis:end{sec:results}")
    edit(paper, "specs/paper.md", "paper#thm:beta", "paper#sec:results")
    project = load_project(paper)
    site = resolve(project, Appearance("paper", "sec:results")).site
    assert site is not None and site.env == "marker"
    assert normalize(project.root.joinpath("paper/paper.tex").read_text()[site.start:site.end],
                     True) == "Opening prose, now pinned."


def test_unbalanced_markers_fail_lint(paper: Path) -> None:
    edit(paper, "paper/paper.tex", "Opening prose", "% specthis:begin{p:open}\nOpening prose")
    messages = [p.message for p in document_problems(load_project(paper))]
    assert any("`specthis:begin{p:open}` is never closed" in m for m in messages)


def test_a_label_defined_twice_has_no_single_span(paper: Path) -> None:
    edit(paper, "paper/paper.tex", "\\label{fig:flow}", "\\label{tab:alpha}")
    project = load_project(paper)
    assert check_project(project)["tab-alpha"].certification is Certification.UNIMPLEMENTED
    assert any("defined 2 times" in p.message for p in document_problems(project))


def test_a_commented_out_label_does_not_count(paper: Path) -> None:
    edit(paper, "paper/paper.tex", "\\label{thm:beta}", "% \\label{thm:beta}")
    assert resolve(load_project(paper), Appearance("paper", "thm:beta")).site is None


def test_a_document_may_span_several_files(paper: Path) -> None:
    write(paper, "paper/sections/appendix.tex",
          "\\begin{table}\\caption{More}\\label{tab:more}\\end{table}\n")
    edit(paper, "specs/bindings.toml", 'path         = "paper/paper.tex"',
         'path         = ["paper/paper.tex", "paper/sections/*.tex"]')
    site = resolve(load_project(paper), Appearance("paper", "tab:more")).site
    assert site is not None and site.file == "paper/sections/appendix.tex"


def test_one_derivation_reads_a_document_once(paper: Path) -> None:
    reads: list[str] = []
    with hashing.observing(lambda path, n, s, cached: reads.append(str(path)) if not cached
                           else None):
        check_project(load_project(paper))
    assert sum(1 for r in reads if r.endswith("paper.tex")) == 1


# ---------------------------------------------------------- normalization


def test_a_reflow_or_a_comment_moves_no_span() -> None:
    """Co-authors reflow constantly; a judgment must not expire on it."""
    a = "\\caption{Alpha}\nthe loss is recorded\nat convergence."
    b = "\\caption{Alpha}   the loss is recorded at   % reflowed\n convergence."
    assert normalize(a, True) == normalize(b, True)


def test_a_comment_eats_its_line_break_as_tex_does() -> None:
    assert normalize("foo%\n   bar", True) == "foobar"
    assert normalize("50\\% of wages", True) == "50\\% of wages"
    assert normalize("line\\\\% comment\nnext", True) == "line\\\\next"


def test_percent_is_printed_text_outside_latex() -> None:
    assert normalize("grew by 3.2% over the period", False) == "grew by 3.2% over the period"


# ------------------------------------------------------------ certification


def test_an_exhibit_is_vouched_against_the_document(paper: Path) -> None:
    make_ready(paper)
    assert cert(paper, "tab-alpha") is Certification.UNVOUCHED
    vouch(paper, "tab-alpha")
    assert cert(paper, "tab-alpha") is Certification.CERTIFIED
    row = read_vouches(paper / "specs")["tab-alpha"]
    assert set(row.code_manifest) == {"doc:paper#tab:alpha", "spec:fit-alpha"}
    assert row.code_manifest["spec:fit-alpha"] == load_project(paper).entries["fit-alpha"].contract_sha


def test_editing_the_span_expires_that_exhibit_and_no_other(paper: Path) -> None:
    make_ready(paper)
    vouch(paper, "tab-alpha")
    vouch(paper, "thm-beta")
    edit(paper, "paper/paper.tex", "recorded at convergence", "recorded at iteration 10")
    reports = check_project(load_project(paper))
    assert reports["tab-alpha"].certification is Certification.UNVOUCHED
    assert reports["tab-alpha"].expired == ["~doc:paper#tab:alpha"]
    assert reports["thm-beta"].certification is Certification.CERTIFIED


def test_editing_elsewhere_in_the_document_expires_nothing(paper: Path) -> None:
    make_ready(paper)
    vouch(paper, "tab-alpha")
    vouch(paper, "thm-beta")
    edit(paper, "paper/paper.tex", "Opening prose, outside every span.", "Rewritten intro.")
    edit(paper, "paper/paper.tex", "A schematic", "A redrawn schematic")
    reports = check_project(load_project(paper))
    assert reports["tab-alpha"].certification is Certification.CERTIFIED
    assert reports["thm-beta"].certification is Certification.CERTIFIED


def test_editing_a_consumed_contract_expires_the_exhibit(paper: Path) -> None:
    make_ready(paper)
    vouch(paper, "tab-alpha")
    edit(paper, "specs/compute-alpha.md", "converge and record its loss",
         "converge and record its final loss")
    r = check_project(load_project(paper))["tab-alpha"]
    assert r.certification is Certification.UNVOUCHED
    assert r.expired == ["~spec:fit-alpha"]


def test_a_consumed_entrys_shared_prose_is_part_of_its_contract(paper: Path) -> None:
    """The `## Script` prose is part of every entry's contract (§5.2b),
    so the description of that entry expires with it."""
    make_ready(paper)
    vouch(paper, "tab-alpha")
    edit(paper, "specs/compute-alpha.md", "Fit the alpha model", "Fit the alpha model by ML")
    assert cert(paper, "tab-alpha") is Certification.UNVOUCHED


def test_moving_the_manuscript_expires_nothing(paper: Path) -> None:
    """A contract names the document, so a move is one map edit."""
    make_ready(paper)
    vouch(paper, "tab-alpha")
    (paper / "paper/paper.tex").rename(paper / "paper/main.tex")
    edit(paper, "specs/bindings.toml", '"paper/paper.tex"', '"paper/main.tex"')
    assert cert(paper, "tab-alpha") is Certification.CERTIFIED


def test_a_documents_lint_configuration_moves_no_digest(paper: Path) -> None:
    """`environments` and `unbacked` configure the orphan lint only —
    `specs/AGENTS.md` and `/specthis-lint` tell agents editing them is
    free. Pinned here because they lean on it."""
    make_ready(paper)
    vouch(paper, "tab-alpha")
    before = code_manifest(load_project(paper), load_project(paper).entries["tab-alpha"])
    edit(paper, "specs/bindings.toml", 'environments = ["table", "theorem"]',
         'environments = ["figure"]\nunbacked = ["fig:flow"]')
    project = load_project(paper)
    assert code_manifest(project, project.entries["tab-alpha"]) == before
    assert cert(paper, "tab-alpha") is Certification.CERTIFIED


def test_a_missing_span_is_unimplemented_and_vouch_refuses(paper: Path) -> None:
    edit(paper, "specs/paper.md", "paper#tab:alpha", "paper#tab:gone")
    assert cert(paper, "tab-alpha") is Certification.UNIMPLEMENTED
    result = run_cli("vouch", "tab-alpha", "--as", "ben", "--path", str(paper))
    assert result.exit_code != 0
    assert "no `\\label{tab:gone}` in paper" in result.output


def test_a_rejection_binds_at_the_pinned_table(paper: Path) -> None:
    """§8.2: an ok over a standing rejection is refused until a digest
    moves — here, the span. The rejection is the recorded discrepancy."""
    make_ready(paper)
    vouch(paper, "tab-alpha", "--reject", "--note", "note says iteration 10")
    assert cert(paper, "tab-alpha") is Certification.REJECTED
    result = run_cli("vouch", "tab-alpha", "--as", "carol", "--path", str(paper))
    assert result.exit_code != 0 and "standing rejection" in result.output

    edit(paper, "paper/paper.tex", "recorded at convergence", "recorded once converged")
    assert cert(paper, "tab-alpha") is Certification.UNVOUCHED
    vouch(paper, "tab-alpha")
    assert cert(paper, "tab-alpha") is Certification.CERTIFIED


# ---------------------------------------------------------------- run axis


def test_an_exhibit_lives_on_the_vouch_tree_alone(paper: Path) -> None:
    make_ready(paper)
    reports = check_project(load_project(paper))
    assert reports["tab-alpha"].realization is None
    vouch_counts, run_counts = tally(reports)
    assert sum(vouch_counts.values()) == 5 and sum(run_counts.values()) == 3


def test_an_exhibit_waits_on_the_machines_behind_it(paper: Path) -> None:
    make_ready(paper)
    vouch(paper, "tab-alpha")
    write(paper, "results/alpha/fit.json", '{"loss": 9}')  # an artefact edited on disk
    r = check_project(load_project(paper))["tab-alpha"]
    assert r.certification is Certification.CERTIFIED
    assert not r.realized, "printed results resting on stale bytes are not verified"


# -------------------------------------------------------------------- lint


def test_lint_names_a_label_no_exhibit_claims(paper: Path) -> None:
    edit(paper, "specs/bindings.toml", 'environments = ["table", "theorem"]',
         'environments = ["table", "theorem", "figure"]')
    messages = [w.message for w in document_warnings(load_project(paper))]
    assert any("figure `fig:flow` is claimed by no exhibit" in m for m in messages)
    assert not any("tab:alpha" in m for m in messages), "claimed labels are not orphans"


def test_a_label_of_an_unpoliced_class_is_not_an_orphan(paper: Path) -> None:
    messages = [w.message for w in document_warnings(load_project(paper))]
    assert not any("fig:flow" in m for m in messages)


def test_a_starred_environment_counts_as_its_class(paper: Path) -> None:
    edit(paper, "paper/paper.tex", "\\begin{figure}\n  \\caption{A schematic}\\label{fig:flow}\n\\end{figure}",
         "\\begin{table*}\\caption{Wide}\\label{tab:wide}\\end{table*}")
    messages = [w.message for w in document_warnings(load_project(paper))]
    assert any("`tab:wide` is claimed by no exhibit" in m for m in messages)


def test_an_unbacked_label_is_not_an_orphan(paper: Path) -> None:
    edit(paper, "specs/bindings.toml", 'environments = ["table", "theorem"]',
         'environments = ["table", "theorem", "figure"]\nunbacked = ["fig:flow"]')
    assert not [w for w in document_warnings(load_project(paper)) if "fig:flow" in w.message]


def test_the_unbacked_list_is_checked_against_the_document(paper: Path) -> None:
    edit(paper, "specs/bindings.toml", 'environments = ["table", "theorem"]',
         'environments = ["table", "theorem"]\nunbacked = ["fig:gone", "tab:alpha"]')
    messages = [w.message for w in document_warnings(load_project(paper))]
    assert any("`fig:gone` as unbacked, but paper defines no such label" in m for m in messages)
    assert any("`tab:alpha` as unbacked, yet tab-alpha claims it" in m for m in messages)


def test_an_unclaimed_marker_is_an_orphan(paper: Path) -> None:
    edit(paper, "paper/paper.tex", "Opening prose, outside every span.",
         "% specthis:begin{p:growth}\nWages grew 3\\%.\n% specthis:end{p:growth}")
    messages = [w.message for w in document_warnings(load_project(paper))]
    assert any("marked span `p:growth` is claimed by no exhibit" in m for m in messages)


def test_lint_verb_reports_orphans_as_warnings(paper: Path) -> None:
    edit(paper, "specs/bindings.toml", 'environments = ["table", "theorem"]',
         'environments = ["table", "theorem", "figure"]')
    result = run_cli("lint", "--path", str(paper))
    assert result.exit_code == 0, result.output
    assert "warning: paper (paper/paper.tex:20): figure `fig:flow`" in result.output


# ------------------------------------------------------------------ status


def test_status_rolls_up_each_document(paper: Path) -> None:
    make_ready(paper)
    vouch(paper, "tab-alpha")
    edit(paper, "specs/bindings.toml", 'environments = ["table", "theorem"]',
         'environments = ["table", "theorem", "figure"]')
    result = run_cli("status", "--path", str(paper))
    assert result.exit_code == 0, result.output
    line = next(ln for ln in result.output.splitlines() if ln.startswith("paper"))
    assert "1/2 described" in line and "1 unvouched" in line and "1 orphan" in line


def test_status_names_the_lines_a_critic_must_read(paper: Path) -> None:
    result = run_cli("status", "tab-alpha", "--path", str(paper))
    assert result.exit_code == 0, result.output
    assert "appears:   paper#tab:alpha  ->  paper/paper.tex:8-13 (table)" in result.output


# ---------------------------------------------------- nothing else changes


def test_a_project_without_exhibits_pins_nothing_new(root: Path) -> None:
    """No exhibit entries: no `doc:`/`spec:` rows, no document line, and
    the code manifests are exactly the scripts and the blob."""
    make_ready(root)
    project = load_project(root)
    assert project.documents == {}
    for row in read_vouches(root / "specs").values():
        assert not any(k.startswith(("doc:", "spec:")) for k in row.code_manifest)
    manifest = code_manifest(project, project.entries["fit-alpha"])
    assert set(manifest) == {"scripts/fit_alpha.py", "package"}
    status = run_cli("status", "--path", str(root)).output.splitlines()
    assert [ln.split()[0] for ln in status] == ["vouch", "run"]


def test_span_sha_is_none_for_an_unresolved_appearance(paper: Path) -> None:
    project = load_project(paper)
    assert span_sha(project, Appearance("paper", "tab:nowhere")) is None
    assert span_sha(project, Appearance("paper", "tab:alpha")) is not None


def test_an_exhibit_has_no_run_claim_to_adopt(paper: Path) -> None:
    from specthis.adopt import AdoptError, adopt_manifest

    manifest = {"manifest_version": 1, "exit_code": 0, "outputs": {"x": "y"}}
    with pytest.raises(AdoptError, match="is an exhibit"):
        adopt_manifest(load_project(paper), "tab-alpha", manifest)


def test_an_exhibit_may_appear_in_several_documents(paper: Path) -> None:
    """Paper and slides print the same table: each appearance is
    pinned, so editing either expires the one claim over both."""
    write(paper, "slides/slides.tex",
          "\\begin{frame}\\begin{table}\\caption{Alpha}\\label{tab:alpha}\\end{table}\\end{frame}\n")
    bindings = paper / "specs/bindings.toml"
    bindings.write_text(bindings.read_text() + '\n[documents.slides]\npath = "slides/slides.tex"\n')
    edit(paper, "specs/paper.md", "- appears: paper#tab:alpha",
         "- appears: paper#tab:alpha, slides#tab:alpha")
    make_ready(paper)
    vouch(paper, "tab-alpha")
    row = read_vouches(paper / "specs")["tab-alpha"]
    assert {"doc:paper#tab:alpha", "doc:slides#tab:alpha"} <= set(row.code_manifest)

    edit(paper, "slides/slides.tex", "Alpha", "Alpha, abridged")
    r = check_project(load_project(paper))["tab-alpha"]
    assert r.certification is Certification.UNVOUCHED
    assert r.expired == ["~doc:slides#tab:alpha"]


def test_a_dormant_exhibit_still_claims_its_label(paper: Path) -> None:
    """A dormant contract is still a contract: skipping the spec takes
    the exhibit out of the queues, not its label back into the orphans."""
    edit(paper, "specs/paper.md", "title: The paper", "title: The paper\nskip: true")
    project = load_project(paper)
    assert "tab-alpha" not in project.entries
    assert not [w for w in document_warnings(project) if "tab:alpha" in w.message]
