"""Code identity as a file (spec §6)."""

import json
from pathlib import Path

from click.testing import CliRunner

from specthis.certificates import content, path_for, render, write_all
from specthis.cli import main
from specthis.parse import load_project

from .conftest import write


def test_certificate_carries_code_identity_only(root: Path) -> None:
    """No verdict, no spec_sha, no timestamp: vouching something must
    not rebuild it, and rewording prose must not either."""
    project = load_project(root)
    doc = content(project, project.entries["fit-alpha"])
    assert doc["certificate_version"] == 1
    assert doc["entry"] == "fit-alpha"
    assert set(doc["code"]) == {"scripts/fit_alpha.py"}
    assert "package" in doc  # the fixture declares [package] globs
    assert not {"verdict", "spec_sha", "when", "vouched"} & set(doc)


def test_serialization_is_deterministic(root: Path) -> None:
    """Regenerating unchanged code must be byte-identical, or every
    regeneration would bust every cache."""
    project = load_project(root)
    doc = content(project, project.entries["fit-alpha"])
    assert render(doc) == render(content(load_project(root), project.entries["fit-alpha"]))


def test_write_all_is_idempotent(root: Path) -> None:
    project = load_project(root)
    write_all(project)
    target = path_for(project, "fit-alpha")
    before = target.stat().st_mtime_ns
    write_all(load_project(root))
    assert target.stat().st_mtime_ns == before, "an unchanged certificate must not be rewritten"


def test_a_code_edit_moves_the_certificate(root: Path) -> None:
    project = load_project(root)
    write_all(project)
    first = path_for(project, "fit-alpha").read_text()
    write(root, "scripts/fit_alpha.py", "# rewritten\n")
    write_all(load_project(root))
    assert path_for(project, "fit-alpha").read_text() != first


def test_a_package_edit_moves_every_certificate(root: Path) -> None:
    """What the certificate is for: a glob has no stable file list, so
    its composed digest can only reach a manager as a file."""
    project = load_project(root)
    write_all(project)
    first = path_for(project, "fit-beta").read_text()
    write(root, "src/pkg/helpers.py", "X = 2\n")
    write_all(load_project(root))
    assert path_for(project, "fit-beta").read_text() != first


def test_certify_verb(root: Path) -> None:
    result = CliRunner().invoke(main, ["certify", "--path", str(root)])
    assert result.exit_code == 0, result.output
    assert "certificate(s)" in result.output
    doc = json.loads((root / "specs/certificates/fit-alpha.json").read_text())
    assert doc["entry"] == "fit-alpha"


def test_entries_without_code_get_no_certificate(root: Path) -> None:
    project = load_project(root)
    written = {p.stem for p in write_all(project)}
    assert all(project.entries[n].binding.scripts for n in written)
