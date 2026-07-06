from pathlib import Path

import pytest

from specthis.parse import SpecError, load_project, parse_spec

from .conftest import COMPUTE_ALPHA, write


def test_project_parses(root: Path) -> None:
    project = load_project(root)
    assert set(project.entries) == {"fit-alpha", "fit-beta", "fig-beta"}
    assert project.package_globs == ["src/pkg/**/*.py"]

    alpha = project.entries["fit-alpha"]
    assert alpha.outputs == ["results/alpha/fit.json"]
    assert alpha.tier == "quick"
    assert alpha.binding.scripts == ["scripts/fit_alpha.py"]
    assert alpha.binding.workflows == ["hut.fit-alpha.json"]
    assert alpha.spec.references == ["models.md"]

    fig = project.entries["fig-beta"]
    assert fig.outputs == ["reports/fig_beta.tex", "reports/fig_beta.dat"]
    assert fig.consumes == ["fit-beta"]


def test_spec_sha_covers_frontmatter(root: Path) -> None:
    before = parse_spec(root / "specs/compute-alpha.md").spec_sha
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("tier: quick", "tier: intensive"))
    after = parse_spec(root / "specs/compute-alpha.md").spec_sha
    assert before != after  # frontmatter edits count as contract edits


def test_default_binding_convention(root: Path) -> None:
    (root / "specs/bindings.toml").unlink()
    project = load_project(root)
    b = project.entries["fit-alpha"].binding
    assert b.scripts == ["scripts/fit-alpha.py"]
    assert b.run == "python scripts/fit-alpha.py"
    assert project.package_globs == []


def test_compute_tier_defaults_intensive(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("tier: quick\n", ""))
    project = load_project(root)
    assert project.entries["fit-alpha"].tier == "intensive"
    assert project.entries["fig-beta"].tier == "quick"  # report defaults quick


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda t: t.replace("references:", "depends_on:"), "retired"),
        (lambda t: t.replace("kind: compute", "kind: banana"), "not one of"),
        (lambda t: t.replace("name: compute-alpha", "name: wrong"), "filename stem"),
        (lambda t: t.replace("Output: `results/alpha/fit.json`", ""), "no `Output:` path"),
        (
            lambda t: t.replace(
                "Output: `results/alpha/fit.json`",
                "Output: `a.json` `b.json`",
            ),
            "exactly one output",
        ),
        (lambda t: t.replace("tier: quick", "tier: warm"), "not one of"),
    ],
)
def test_grammar_violations(root: Path, mutation, match: str) -> None:
    write(root, "specs/compute-alpha.md", mutation(COMPUTE_ALPHA))
    with pytest.raises(SpecError, match=match):
        load_project(root)


def test_missing_frontmatter(root: Path) -> None:
    write(root, "specs/compute-alpha.md", "# no frontmatter\n")
    with pytest.raises(SpecError, match="frontmatter"):
        load_project(root)


def test_duplicate_entry_names(root: Path) -> None:
    write(root, "specs/compute-dup.md", COMPUTE_ALPHA.replace("compute-alpha", "compute-dup"))
    with pytest.raises(SpecError, match="duplicate entry"):
        load_project(root)


def test_unknown_consumes_and_references(root: Path) -> None:
    write(root, "specs/compute-beta.md", (root / "specs/compute-beta.md").read_text().replace("fit-alpha", "fit-nowhere"))
    with pytest.raises(SpecError, match="unknown entry"):
        load_project(root)
    write(root, "specs/compute-beta.md", (root / "specs/compute-beta.md").read_text().replace("fit-nowhere", "fit-alpha"))
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("models.md", "ghosts.md"))
    with pytest.raises(SpecError, match="unknown spec"):
        load_project(root)


def test_export_outputs_inline_form(root: Path) -> None:
    text = (root / "specs/report-beta.md").read_text()
    text = text.replace(
        "Export outputs:\n- `reports/fig_beta.tex`\n- `reports/fig_beta.dat`",
        "Export outputs: `reports/fig_beta.tex` and `reports/fig_beta.dat`",
    )
    write(root, "specs/report-beta.md", text)
    project = load_project(root)
    assert project.entries["fig-beta"].outputs == [
        "reports/fig_beta.tex",
        "reports/fig_beta.dat",
    ]
