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


# ------------------------------------------------- per-instance claims


def report_keys(root: Path) -> set:
    from specthis.check import check_project

    return set(check_project(load_project(root)))


def test_check_reports_one_row_per_instance(root: Path) -> None:
    templated(root)
    keys = report_keys(root)
    assert "clean-wages" not in keys, "the template itself is not a claim"
    assert {"clean-wages[dataset=chile]", "clean-wages[dataset=argentina]"} <= keys


def test_a_template_vouch_certifies_every_instance(root: Path) -> None:
    """One vouch covers the template — the ceremony win, and the reason
    it is the strongest claim a mind can be asked to sign."""
    from click.testing import CliRunner

    from specthis.check import Certification, check_project
    from specthis.cli import main

    templated(root)
    CliRunner().invoke(main, ["vouch", "clean-wages", "--as", "reviewer", "--path", str(root)])
    reports = check_project(load_project(root))
    assert all(
        reports[k].certification is Certification.CERTIFIED
        for k in ("clean-wages[dataset=chile]", "clean-wages[dataset=argentina]")
    )


def test_an_instance_vouch_covers_only_that_instance(root: Path) -> None:
    """Sign instances when the transformation is not data-agnostic."""
    from specthis.check import Certification, check_project
    from specthis.ledger import Vouch, record_vouch

    templated(root)
    project = load_project(root)
    entry = project.entries["clean-wages"]
    from specthis.check import code_sha

    record_vouch(project.specs_dir, "clean-wages[dataset=chile]", Vouch(
        spec_sha=entry.spec.spec_sha,
        code_sha=code_sha(project, entry),
        verdict="ok",
        attester="reviewer",
        vouched="2026-01-01T00:00:00+00:00",
        spec_block_sha=entry.block_sha,
    ))
    reports = check_project(load_project(root))
    assert reports["clean-wages[dataset=chile]"].certification is Certification.CERTIFIED
    assert reports["clean-wages[dataset=argentina]"].certification is Certification.UNVOUCHED


def test_instances_carry_their_own_props_and_template(root: Path) -> None:
    from specthis.check import check_project

    templated(root)
    r = check_project(load_project(root))["clean-wages[dataset=chile]"]
    assert r.instance_of == "clean-wages" and r.props == {"dataset": "chile"}


def test_each_instance_pins_its_own_step(root: Path) -> None:
    """Rewiring one instance's step must not touch its siblings."""
    from specthis.check import check_project

    templated(root)
    reports = check_project(load_project(root))
    chile = reports["clean-wages[dataset=chile]"].run
    assert chile is None  # never run yet
    from specthis.check import instance_inputs
    from specthis.instances import instances as insts

    project = load_project(root)
    entry = project.entries["clean-wages"]
    tables = {
        i.name: instance_inputs(project, entry, i, {}, {}) for i in insts(project, entry)
    }
    a, b = tables["clean-wages[dataset=chile]"], tables["clean-wages[dataset=argentina]"]
    assert a["step:clean-wages[dataset=chile]"] != b["step:clean-wages[dataset=argentina]"]


def test_instances_are_realized_independently(root: Path) -> None:
    from click.testing import CliRunner

    from specthis.check import Realization, check_project
    from specthis.cli import main

    templated(root)
    write(root, "scripts/clean_wages.py",
          "import pathlib,sys\n"
          "d=sys.argv[1]\n"
          "p=pathlib.Path(f'data/{d}'); p.mkdir(parents=True, exist_ok=True)\n"
          "(p/'wages.parquet').write_text(d)\n")
    result = CliRunner().invoke(main, ["build", "--path", str(root)])
    assert result.exit_code == 0, result.output
    reports = check_project(load_project(root))
    assert reports["clean-wages[dataset=chile]"].realization is Realization.CURRENT
    assert reports["clean-wages[dataset=argentina]"].realization is Realization.CURRENT
