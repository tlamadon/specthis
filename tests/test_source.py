"""Source entries: bytes from outside any pipeline (§2), and `record`."""

from pathlib import Path

from click.testing import CliRunner

from specthis.check import Certification, Realization, check_project, is_source
from specthis.cli import main
from specthis.ledger import read_runs
from specthis.parse import load_project

from .conftest import write

SOURCE_SPEC = """\
---
group: data
---

# Raw wages

### raw-wages

IPUMS extract #14, men 25–55. Education recoded upstream — see the
codebook oddity on `educ99`. Never re-download without bumping the
extract number here.

- produces: data/raw/wages.parquet
"""


def sourced(root: Path) -> Path:
    write(root, "specs/raw-wages.md", SOURCE_SPEC)
    return root


def run_cli(*a: str):
    return CliRunner().invoke(main, list(a))


def test_a_physical_path_and_no_code_infers_a_source(root: Path) -> None:
    sourced(root)
    entry = load_project(root).entries["raw-wages"]
    assert is_source(entry)
    assert entry.outputs == ["data/raw/wages.parquet"]


def test_a_source_needs_no_code_to_be_certifiable(root: Path) -> None:
    """It computes nothing: the subject of the claim is the data."""
    sourced(root)
    write(root, "data/raw/wages.parquet", "bytes")
    reports = check_project(load_project(root))
    assert reports["raw-wages"].certification is Certification.UNVOUCHED
    assert reports["raw-wages"].certification is not Certification.UNIMPLEMENTED


def test_record_pins_the_bytes_without_running_anything(root: Path) -> None:
    sourced(root)
    write(root, "data/raw/wages.parquet", "bytes")
    result = run_cli("record", "raw-wages", "--path", str(root))
    assert result.exit_code == 0, result.output
    row = read_runs(root / "specs")["raw-wages"]
    assert row.executor == "hand"
    assert row.outputs == {"data/raw/wages.parquet": row.output_sha}
    assert check_project(load_project(root))["raw-wages"].realization is Realization.CURRENT


def test_record_refuses_when_the_bytes_are_not_there(root: Path) -> None:
    sourced(root)
    result = run_cli("record", "raw-wages", "--path", str(root))
    assert result.exit_code != 0
    assert "place the file first" in result.output


def test_record_never_writes_a_vouch(root: Path) -> None:
    """Provenance is a judgment: recording bytes is not attesting them."""
    sourced(root)
    write(root, "data/raw/wages.parquet", "bytes")
    run_cli("record", "raw-wages", "--path", str(root))
    assert not (root / "specs/vouches.toml").exists()


def test_replacing_the_data_expires_its_provenance_vouch(root: Path) -> None:
    sourced(root)
    write(root, "data/raw/wages.parquet", "extract 14")
    run_cli("record", "raw-wages", "--path", str(root))
    run_cli("vouch", "raw-wages", "--as", "reviewer", "--path", str(root))
    assert check_project(load_project(root))["raw-wages"].certification is Certification.CERTIFIED

    write(root, "data/raw/wages.parquet", "extract 15")
    assert check_project(load_project(root))["raw-wages"].certification is Certification.UNVOUCHED


def test_a_source_must_have_no_pipeline_step(root: Path) -> None:
    from specthis.correspond import correspondence_problems

    sourced(root)
    write(root, "data/raw/wages.parquet", "bytes")
    write(root, "pipeline.toml",
          '[steps.raw-wages]\ncommand = "true"\nouts = ["data/raw/wages.parquet"]\n')
    problems = [p.message for p in correspondence_problems(load_project(root))]
    assert any("is a source entry and must have no step" in m for m in problems)
