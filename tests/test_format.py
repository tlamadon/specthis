"""The target spec format (§3), accepted alongside the legacy one."""

from pathlib import Path

from specthis.instances import is_template
from specthis.parse import load_project, load_project_lenient

from .conftest import write

NEW_FORMAT = """\
---
name: wages
kind: compute
---

# Wage data

Opening prose is narrative: signed by no one.

### clean-wages

Drop negative wages, winsorize at the 99th percentile.

- consumes: fit-alpha
- produces: data/wages.parquet
"""


def test_entry_fields_supply_edges_and_outputs(root: Path) -> None:
    write(root, "specs/wages.md", NEW_FORMAT)
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[entries.clean-wages]\nscripts = ["scripts/fit_alpha.py"]\n')
    entry = load_project(root).entries["clean-wages"]
    assert entry.consumes == ["fit-alpha"]
    assert entry.outputs == ["data/wages.parquet"]


def test_per_entry_edges_are_validated_like_file_level_ones(root: Path) -> None:
    """An unknown upstream is dropped and reported, never left to crash
    a lookup downstream."""
    write(root, "specs/wages.md", NEW_FORMAT.replace("fit-alpha", "no-such-entry"))
    _, problems = load_project_lenient(root)
    assert any("consumes unknown entry `no-such-entry`" in p.message for p in problems)


def test_an_unknown_entry_field_is_an_error(root: Path) -> None:
    write(root, "specs/wages.md", NEW_FORMAT + "- consume: typo\n")
    _, problems = load_project_lenient(root)
    assert any("unknown entry field `consume`" in p.message for p in problems)


def test_props_may_be_declared_per_entry(root: Path) -> None:
    write(root, "specs/wages.md", NEW_FORMAT.replace(
        "- produces: data/wages.parquet", "- props: dataset\n- produces: data/{dataset}/w.parquet"
    ))
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[entries.clean-wages]\nscripts = ["scripts/fit_alpha.py"]\n')
    entry = load_project(root).entries["clean-wages"]
    assert entry.props == ["dataset"]
    assert is_template(entry)


def test_the_legacy_format_still_parses(root: Path) -> None:
    """Both forms are accepted, so a project migrates at its own pace."""
    project = load_project(root)
    assert project.entries["fit-alpha"].outputs == ["results/alpha/fit.json"]
    assert project.entries["fit-beta"].consumes == ["fit-alpha"]


MINIMAL = """\
---
group: data
---

# Wage data

### clean-wages

Drop negative wages, winsorize at the 99th percentile.

- consumes: fit-alpha
- produces: data/wages.parquet
"""


def bind_entry(root: Path) -> None:
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[entries.clean-wages]\nscripts = ["scripts/fit_alpha.py"]\n')


def test_kind_and_name_are_optional(root: Path) -> None:
    """§2: type is a consequence of the fields entries declare."""
    write(root, "specs/wages.md", MINIMAL)
    bind_entry(root)
    project = load_project(root)
    assert project.entries["clean-wages"].spec.kind == "compute"
    assert project.entries["clean-wages"].spec.name == "wages"


def test_a_bare_code_field_infers_a_library(root: Path) -> None:
    write(root, "specs/helpers.md",
          "---\ngroup: code\n---\n\n# Helpers\n\n### wage-helpers\n\n"
          "`winsor(x, p)` truncates symmetrically.\n\n- code\n")
    write(root, "specs/bindings.toml",
          (root / "specs/bindings.toml").read_text()
          + '\n[entries.wage-helpers]\nscripts = ["scripts/fit_alpha.py"]\n')
    project = load_project(root)
    assert project.entries["wage-helpers"].spec.kind == "library"


def test_a_prose_only_file_needs_no_kind(root: Path) -> None:
    write(root, "specs/notes.md", "---\ngroup: notes\n---\n\n# Notes\n\nJust prose.\n")
    project = load_project(root)
    assert any(s.name == "notes" and s.kind == "definitions" for s in project.specs)


def test_a_wrong_explicit_name_is_still_an_error(root: Path) -> None:
    write(root, "specs/wages.md", MINIMAL.replace("---\ngroup: data", "---\nname: wrong\ngroup: data"))
    _, problems = load_project_lenient(root)
    assert any("must match the filename stem" in p.message for p in problems)
