"""Templates: one entry, one binding, N instances (spec §15)."""

from pathlib import Path

from specthis.parse import load_project
from specthis.instances import (
    bind,
    instances,
    is_template,
    resolve,
    template_problems,
)

from .conftest import PY, write

TEMPLATE_SPEC = """\
---
name: clean-wages
kind: compute
props: dataset
---

# Wage cleaning

### clean-wages

Drop negative wages, winsorize at the 99th percentile. Applies to any
country panel carrying the standard column set.

Output: `data/{dataset}/wages.parquet`
"""

BASE_STEPS = f"""\
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

TEMPLATE_PIPELINE = BASE_STEPS + f"""
[steps.clean-chile]
command = '{PY} scripts/clean_wages.py chile'
deps    = ["scripts/clean_wages.py"]
outs    = ["data/chile/wages.parquet"]

[steps.clean-argentina]
command = '{PY} scripts/clean_wages.py argentina'
deps    = ["scripts/clean_wages.py"]
outs    = ["data/argentina/wages.parquet"]
"""


def templated(root: Path) -> Path:
    write(root, "specs/clean-wages.md", TEMPLATE_SPEC)
    write(root, "pipeline.toml", TEMPLATE_PIPELINE)
    write(root, "scripts/clean_wages.py", "pass\n")
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[entries.clean-wages]\nscripts = ["scripts/clean_wages.py"]\n')
    return root


# ------------------------------------------------------------- patterns


def test_bind_extracts_prop_values_from_a_path() -> None:
    assert bind("data/{dataset}/wages.parquet", "data/chile/wages.parquet") == {
        "dataset": "chile"
    }
    assert bind("data/{dataset}/wages.parquet", "data/other/fit.json") is None


def test_a_prop_never_spans_a_directory_separator() -> None:
    """A prop is a short scalar distinguishing coexisting instances, not
    a path fragment — otherwise one pattern would swallow a whole tree."""
    assert bind("data/{d}/wages.parquet", "data/a/b/wages.parquet") is None


def test_resolve_is_the_inverse_of_bind() -> None:
    pattern = "results/{sample}-{period}/fit.json"
    path = "results/men-early/fit.json"
    assert resolve(pattern, bind(pattern, path)) == path


# ------------------------------------------------------------ instances


def test_instances_come_from_the_pipeline_not_a_registry(root: Path) -> None:
    project = load_project(templated(root))
    entry = project.entries["clean-wages"]
    assert is_template(entry)
    found = instances(project, entry)
    assert [i.name for i in found] == [
        "clean-wages[dataset=argentina]",
        "clean-wages[dataset=chile]",
    ]


def test_identity_comes_from_the_output_path_not_the_step_id(root: Path) -> None:
    """No naming convention is imposed on the backend: the steps here
    are called clean-chile and clean-argentina, not clean-wages@chile."""
    templated(root)
    project = load_project(root)
    found = {i.name: i for i in instances(project, project.entries["clean-wages"])}
    chile = found["clean-wages[dataset=chile]"]
    assert chile.step == "clean-chile"
    assert chile.outputs == ("data/chile/wages.parquet",)
    assert chile.binding == {"dataset": "chile"}


def test_no_pipeline_means_no_instances(root: Path) -> None:
    write(root, "specs/clean-wages.md", TEMPLATE_SPEC)
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[entries.clean-wages]\nscripts = ["scripts/clean_wages.py"]\n')
    project = load_project(root)
    assert instances(project, project.entries["clean-wages"]) == []


def test_a_step_producing_half_an_instance_is_not_accepted(root: Path) -> None:
    """Every output pattern must bind consistently, or one set of prop
    values would not explain the whole step."""
    write(root, "specs/clean-wages.md", TEMPLATE_SPEC.replace(
        "Output: `data/{dataset}/wages.parquet`",
        "Export outputs:\n- `data/{dataset}/wages.parquet`\n- `data/{dataset}/log.txt`",
    ).replace("kind: compute", "kind: report"))
    write(root, "pipeline.toml", TEMPLATE_PIPELINE)  # declares no log.txt
    write(root, "scripts/clean_wages.py", "pass\n")
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[entries.clean-wages]\nscripts = ["scripts/clean_wages.py"]\n')
    project = load_project(root)
    assert instances(project, project.entries["clean-wages"]) == []


def test_a_plain_entry_has_no_instances(root: Path) -> None:
    project = load_project(root)
    assert not is_template(project.entries["fit-alpha"])
    assert instances(project, project.entries["fit-alpha"]) == []


# ------------------------------------------------------------- the lint


def test_a_prop_absent_from_an_output_pattern_is_a_problem(root: Path) -> None:
    write(root, "specs/clean-wages.md",
          TEMPLATE_SPEC.replace("props: dataset", "props:\n  - dataset\n  - period"))
    assert any("period" in m and "could collide" in m
               for m in template_problems(load_project(root)))


def test_an_undeclared_placeholder_is_a_problem(root: Path) -> None:
    write(root, "specs/clean-wages.md",
          TEMPLATE_SPEC.replace("data/{dataset}/wages.parquet", "data/{dataset}/{era}/w.parquet"))
    assert any("undeclared prop" in m for m in template_problems(load_project(root)))


def test_a_placeholder_without_props_is_a_problem(root: Path) -> None:
    write(root, "specs/clean-wages.md", TEMPLATE_SPEC.replace("props: dataset\n", ""))
    assert any("declares no props" in m for m in template_problems(load_project(root)))


def test_parameterized_code_is_a_problem(root: Path) -> None:
    """One vouch can cover a template only because every instance runs
    the same code."""
    templated(root)
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text().replace(
              '"scripts/clean_wages.py"', '"scripts/clean_{dataset}.py"'))
    assert any("parameterized" in m for m in template_problems(load_project(root)))


def test_a_faithful_template_has_no_problems(root: Path) -> None:
    assert template_problems(load_project(templated(root))) == []


# ------------------------------------------------------------ lint via cli


def test_lint_accepts_a_template_whose_steps_realize_its_instances(root: Path) -> None:
    from click.testing import CliRunner

    from specthis.cli import main

    templated(root)
    result = CliRunner().invoke(main, ["lint", "--path", str(root)])
    assert result.exit_code == 0, result.output


def test_lint_flags_a_template_with_no_instances(root: Path) -> None:
    from click.testing import CliRunner

    from specthis.cli import main

    templated(root)
    write(root, "pipeline.toml", TEMPLATE_PIPELINE.replace("data/chile", "elsewhere/chile")
          .replace("data/argentina", "elsewhere/argentina"))
    result = CliRunner().invoke(main, ["lint", "--path", str(root)])
    assert result.exit_code == 1
    assert "no instances exist" in result.output
