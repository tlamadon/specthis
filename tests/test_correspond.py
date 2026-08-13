"""Lint replaces a compiler, so it has to be complete (§13).

Every case here is something a generator would have made
unrepresentable. Authoring the pipeline by hand trades that guarantee
for a checked one — these are the checks.
"""

from pathlib import Path

from click.testing import CliRunner

from specthis.cli import main
from specthis.correspond import correspondence_problems, correspondence_warnings
from specthis.parse import load_project

from .conftest import PY, write

PIPELINE = f"""\
[steps.fit-alpha]
command = '{PY} scripts/fit_alpha.py'
deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json"]
outs    = ["results/alpha/fit.json"]

[steps.fit-beta]
command = '{PY} scripts/fit_beta.py'
deps    = ["scripts/fit_beta.py", "results/alpha/fit.json"]
outs    = ["results/beta/fit.json"]

[steps.fig-beta]
command = '{PY} scripts/fig_beta.py'
deps    = ["scripts/fig_beta.py", "results/beta/fit.json"]
outs    = ["reports/fig_beta.tex", "reports/fig_beta.dat"]
"""


def problems(root: Path) -> list[str]:
    return [p.message for p in correspondence_problems(load_project(root))]


def warnings(root: Path) -> list[str]:
    return [p.message for p in correspondence_warnings(load_project(root))]


def piped(root: Path, pipeline: str = PIPELINE) -> Path:
    write(root, "pipeline.toml", pipeline)
    return root


def test_a_faithful_pipeline_has_no_problems(root: Path) -> None:
    assert problems(piped(root)) == []


def test_no_pipeline_means_nothing_to_check(root: Path) -> None:
    """A project that has not adopted a pipeline must not be failed."""
    assert problems(root) == [] and warnings(root) == []


# ------------------------------------------------------ spec <-> pipeline


def test_an_entry_with_no_step_is_declared_but_never_built(root: Path) -> None:
    piped(root, PIPELINE.replace('[steps.fig-beta]', '[steps.unused]'))
    assert any("no step for entry `fig-beta`" in m for m in problems(root))


def test_a_step_matching_no_entry_is_flagged(root: Path) -> None:
    piped(root, PIPELINE + '\n[steps.orphan]\ncommand = "true"\nouts = ["x.txt"]\n')
    assert any("step `orphan` matches no entry" in m for m in problems(root))


# ------------------------------------------------------- map <-> pipeline


def test_judged_code_absent_from_deps_is_an_error(root: Path) -> None:
    """The sharpest rule: the vouch would expire on an edit the manager
    never noticed, so the two axes would disagree about the same file."""
    piped(root, PIPELINE.replace(
        'deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json"]',
        'deps    = ["hut.fit-alpha.json"]',
    ))
    assert any(
        "judged code for `fit-alpha` but is not among step" in m for m in problems(root)
    )


def test_a_declared_output_the_step_does_not_produce_is_an_error(root: Path) -> None:
    piped(root, PIPELINE.replace('outs    = ["results/alpha/fit.json"]', 'outs    = ["other.json"]'))
    assert any("declares output `results/alpha/fit.json`" in m for m in problems(root))


# ---------------------------------------------------------------- edges


def test_a_contract_edge_the_pipeline_does_not_build(root: Path) -> None:
    piped(root, PIPELINE.replace(
        'deps    = ["scripts/fit_beta.py", "results/alpha/fit.json"]',
        'deps    = ["scripts/fit_beta.py"]',
    ))
    assert any("the contract declares an edge the pipeline does not build" in m
               for m in problems(root))


def test_a_pipeline_edge_the_contract_does_not_declare(root: Path) -> None:
    piped(root, PIPELINE.replace(
        'deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json"]',
        'deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json", "results/beta/fit.json"]',
    ))
    assert any("the pipeline builds an edge the contract does not declare" in m
               for m in problems(root))


# -------------------------------------------------------------- warnings


def test_a_command_carrying_flags_warns(root: Path) -> None:
    piped(root, PIPELINE.replace(
        f"{PY} scripts/fit_alpha.py", f"{PY} scripts/fit_alpha.py --winsor 0.99"
    ))
    assert any("carries flags" in m for m in warnings(root))
    assert problems(root) == [], "a warning is not a problem"


def test_an_unclaimed_output_warns(root: Path) -> None:
    piped(root, PIPELINE.replace(
        'outs    = ["reports/fig_beta.tex", "reports/fig_beta.dat"]',
        'outs    = ["reports/fig_beta.tex", "reports/fig_beta.dat", "extra.log"]',
    ))
    assert any("which no entry claims" in m for m in warnings(root))


# ------------------------------------------------------------------ cli


def test_lint_reports_correspondence_and_exits_non_zero(root: Path) -> None:
    piped(root, PIPELINE.replace(
        'deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json"]',
        'deps    = ["hut.fit-alpha.json"]',
    ))
    result = CliRunner().invoke(main, ["lint", "--path", str(root)])
    assert result.exit_code == 1
    assert "judged code" in result.output


def test_lint_is_clean_on_a_faithful_project(root: Path) -> None:
    piped(root)
    result = CliRunner().invoke(main, ["lint", "--path", str(root)])
    assert result.exit_code == 0
    assert "specs are clean" in result.output
