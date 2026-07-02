"""kind: library — vouch-only code entries; the chain stops at code."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.check import Status, check_project
from specthis.cli import main
from specthis.export import render
from specthis.parse import SpecError, load_project

from .conftest import BINDINGS, COMPUTE_BETA, fake_run, vouch_ok, write

ESTIMATORS = """\
---
name: estimators
kind: library
---

# Estimators

## Entries

### estimator-core

The core estimator must resample exactly as specified here.
"""

LIB_BINDING = """
[entries.estimator-core]
scripts = ["src/pkg/estimator.py"]
"""


def add_library(root: Path) -> None:
    """Add a library spec + module, and make fit-beta consume it."""
    write(root, "specs/estimators.md", ESTIMATORS)
    write(root, "specs/bindings.toml", BINDINGS + LIB_BINDING)
    write(root, "src/pkg/estimator.py", "def resample(x):\n    return x\n")
    write(
        root,
        "specs/compute-beta.md",
        COMPUTE_BETA.replace(
            "consumes:\n  - fit-alpha", "consumes:\n  - fit-alpha\n  - estimator-core"
        ),
    )


def ready_all(root: Path) -> None:
    vouch_ok(root, "estimator-core")
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)
        fake_run(root, entry)


def statuses(root: Path) -> dict[str, Status]:
    return {n: r.status for n, r in check_project(load_project(root)).items()}


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


# ---------------------------------------------------------------- parse


def test_library_entry_parses_without_output(root: Path) -> None:
    add_library(root)
    project = load_project(root)
    e = project.entries["estimator-core"]
    assert e.outputs == []
    assert e.binding.scripts == ["src/pkg/estimator.py"]
    assert project.library_scripts == frozenset({"src/pkg/estimator.py"})


def test_library_entry_must_not_declare_output(root: Path) -> None:
    add_library(root)
    write(
        root,
        "specs/estimators.md",
        ESTIMATORS + "\nOutput: `results/nope.json`\n",
    )
    with pytest.raises(SpecError, match="must not declare an output"):
        load_project(root)


def test_library_entry_requires_binding(root: Path) -> None:
    add_library(root)
    write(root, "specs/bindings.toml", BINDINGS)  # binding removed
    with pytest.raises(SpecError, match="needs `scripts` in specs/bindings.toml"):
        load_project(root)


# --------------------------------------------------------------- ladder


def test_library_ladder_stops_at_the_vouch(root: Path) -> None:
    add_library(root)
    (root / "src/pkg/estimator.py").unlink()
    assert statuses(root)["estimator-core"] is Status.UNIMPLEMENTED

    write(root, "src/pkg/estimator.py", "def resample(x):\n    return x\n")
    assert statuses(root)["estimator-core"] is Status.AUDIT_NEEDED

    vouch_ok(root, "estimator-core")
    assert statuses(root)["estimator-core"] is Status.READY  # no run needed, ever


def test_spec_edit_is_finally_picked_up(root: Path) -> None:
    """THE motivating case: an estimators.md edit must reach the ledger."""
    add_library(root)
    ready_all(root)
    assert set(statuses(root).values()) == {Status.READY}

    write(root, "specs/estimators.md", ESTIMATORS + "\nTighter resampling contract.\n")
    s = statuses(root)
    assert s["estimator-core"] is Status.AUDIT_NEEDED  # re-judge the module
    assert s["fit-beta"] is Status.UPSTREAM_UNVERIFIED  # waits on the re-vouch
    assert s["fig-beta"] is Status.UPSTREAM_UNVERIFIED  # transitively
    assert s["fit-alpha"] is Status.READY  # not a consumer; untouched


def test_module_edit_flags_entry_and_stales_consumers_only(root: Path) -> None:
    add_library(root)
    ready_all(root)
    write(root, "src/pkg/estimator.py", "def resample(x):\n    return list(x)\n")
    s = statuses(root)
    assert s["estimator-core"] is Status.AUDIT_NEEDED
    # carved out of the package blob: non-consumers keep their vouch
    assert s["fit-alpha"] is Status.READY
    # consumers must re-run with the new code once the module is re-vouched
    vouch_ok(root, "estimator-core")
    s = statuses(root)
    assert s["estimator-core"] is Status.READY
    assert s["fit-beta"] is Status.STALE
    assert "upstream:estimator-core" in check_project(load_project(root))["fit-beta"].moved

    fake_run(root, "fit-beta")
    fake_run(root, "fig-beta")
    assert set(statuses(root).values()) == {Status.READY}


def test_shared_glue_still_detonates_everything(root: Path) -> None:
    add_library(root)
    ready_all(root)
    write(root, "src/pkg/helpers.py", "X = 2\n")  # in the blob, not library-bound
    s = statuses(root)
    assert s["fit-alpha"] is Status.AUDIT_NEEDED
    assert s["fit-beta"] is Status.AUDIT_NEEDED
    assert s["estimator-core"] is Status.AUDIT_NEEDED  # blob is in its manifest too


# ------------------------------------------------------------------ cli


def test_run_refuses_library_entries(root: Path) -> None:
    add_library(root)
    result = run_cli("run", "estimator-core", "--path", str(root))
    assert result.exit_code != 0
    assert "nothing to run" in result.output


def test_run_stale_rebuilds_consumers_of_a_revouched_module(root: Path) -> None:
    add_library(root)
    ready_all(root)
    write(root, "src/pkg/estimator.py", "def resample(x):\n    return list(x)\n")
    vouch_ok(root, "estimator-core")
    result = run_cli("run", "--stale", "--path", str(root))
    assert result.exit_code == 0, result.output
    # fit-beta re-runs; its output is byte-identical (deterministic script),
    # so fig-beta's signature still holds and it is NOT rebuilt.
    assert "rebuilt 1" in result.output
    assert set(statuses(root).values()) == {Status.READY}


def test_migrate_skips_library_entries(root: Path) -> None:
    add_library(root)
    write(root, "specs/_lock.json", json.dumps({"estimator-core": {"inputs_certified": {}}}))
    result = run_cli("migrate", "--path", str(root))
    assert result.exit_code == 0
    assert "nothing derived to import" in result.output


def test_status_shows_library_shape(root: Path) -> None:
    add_library(root)
    result = run_cli("status", "estimator-core", "--path", str(root))
    assert result.exit_code == 0
    assert "chain stops at code" in result.output
    result = run_cli("status", "--path", str(root))
    assert " library" in result.output and "library/quick" not in result.output


def test_viewer_renders_library_kind(root: Path) -> None:
    add_library(root)
    page, _, _ = render(load_project(root))
    assert "kind-library" in page
    assert "code-only" in page
