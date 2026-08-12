"""End to end across the seam: pipeline -> runner -> manifest -> ledger.

The path the whole architecture rests on. specthis hands over a plan,
a manager makes bytes and reports what it did, and the notary
countersigns — verifying transcription, never derivation.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.adopt import AdoptError, adopt_manifest
from specthis.backends import DONE, FAILED, RunnerBackend
from specthis.check import Realization, check_project
from specthis.cli import main
from specthis.ledger import read_runs
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
"""


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


@pytest.fixture
def piped(root: Path) -> Path:
    write(root, "pipeline.toml", PIPELINE)
    return root


def realization(root: Path, name: str) -> Realization:
    return check_project(load_project(root))[name].realization


# ------------------------------------------------------------ the seam


def test_build_records_claims_the_runner_supports(piped: Path) -> None:
    result = run_cli("build", "--path", str(piped))
    assert result.exit_code == 0, result.output
    assert "adopted fit-alpha" in result.output
    runs = read_runs(piped / "specs")
    assert set(runs) == {"fit-alpha", "fit-beta"}
    assert realization(piped, "fit-alpha") is Realization.CURRENT
    assert realization(piped, "fit-beta") is Realization.CURRENT


def test_adopted_row_carries_per_output_digests(piped: Path) -> None:
    run_cli("build", "--path", str(piped))
    row = read_runs(piped / "specs")["fit-alpha"]
    assert row.outputs == {"results/alpha/fit.json": row.output_sha}
    assert row.executor == "specthis-runner"


def test_build_is_idempotent_and_hits_are_invisible(piped: Path) -> None:
    run_cli("build", "--path", str(piped))
    first = read_runs(piped / "specs")["fit-alpha"]
    result = run_cli("build", "--path", str(piped))
    assert result.exit_code == 0, result.output
    second = read_runs(piped / "specs")["fit-alpha"]
    assert first.output_sha == second.output_sha and first.inputs == second.inputs


def test_build_never_writes_vouches(piped: Path) -> None:
    run_cli("build", "--path", str(piped))
    assert not (piped / "specs/vouches.toml").exists()


def test_a_failing_step_records_nothing_and_exits_non_zero(piped: Path) -> None:
    write(piped, "scripts/fit_alpha.py", "raise SystemExit(3)\n")
    result = run_cli("build", "--path", str(piped))
    assert result.exit_code != 0
    assert not (piped / "specs/runs.toml").exists()


def test_force_needs_entries(piped: Path) -> None:
    result = run_cli("build", "--force", "--path", str(piped))
    assert result.exit_code != 0
    assert "repair, not a mode" in result.output


def test_an_edited_artefact_is_detected_and_rebuilt(piped: Path) -> None:
    """specthis always detects a tampered output (§10.3). Whether the
    manager *rebuilds* it depends on the manager: the bundled runner
    checks its recorded outputs against disk, so a plain build suffices.
    A purely input-keyed manager would report a cache hit, which is why
    --force exists."""
    run_cli("build", "--path", str(piped))
    write(piped, "results/alpha/fit.json", '{"loss": 999}')
    assert realization(piped, "fit-alpha") is Realization.STALE

    assert run_cli("build", "--path", str(piped)).exit_code == 0
    assert realization(piped, "fit-alpha") is Realization.CURRENT


def test_force_bypasses_the_managers_cache(piped: Path) -> None:
    run_cli("build", "--path", str(piped))
    before = read_runs(piped / "specs")["fit-alpha"].ran
    result = run_cli("build", "fit-alpha", "--force", "--path", str(piped))
    assert result.exit_code == 0, result.output
    assert read_runs(piped / "specs")["fit-alpha"].ran >= before
    assert realization(piped, "fit-alpha") is Realization.CURRENT


# ------------------------------------------------------- fail closed


def test_a_manifest_that_disagrees_with_the_bytes_is_refused(piped: Path) -> None:
    project = load_project(piped)
    backend = RunnerBackend(piped)
    handle = backend.submit()
    manifest = backend.manifests(handle)["fit-alpha"]
    forged = {**manifest, "outputs": {k: "0" * 64 for k in manifest["outputs"]}}
    with pytest.raises(AdoptError, match="does not hash"):
        adopt_manifest(project, "fit-alpha", forged)
    assert "fit-alpha" not in read_runs(piped / "specs")


def test_a_failed_manifest_is_never_adopted(piped: Path) -> None:
    project = load_project(piped)
    with pytest.raises(AdoptError, match="failed step"):
        adopt_manifest(project, "fit-alpha", {"manifest_version": 1, "exit_code": 3})


def test_an_unknown_manifest_version_is_refused(piped: Path) -> None:
    project = load_project(piped)
    with pytest.raises(AdoptError, match="manifest_version"):
        adopt_manifest(project, "fit-alpha", {"manifest_version": 99, "exit_code": 0})


# --------------------------------------------------------- the backend


def test_backend_reports_done_and_serves_manifests_for_skipped_steps(piped: Path) -> None:
    backend = RunnerBackend(piped)
    assert backend.poll(backend.submit()) == DONE
    handle = backend.submit()  # everything cached now
    assert backend.poll(handle) == DONE
    assert set(backend.manifests(handle)) == {"fit-alpha", "fit-beta"}


def test_backend_reports_failed(piped: Path) -> None:
    write(piped, "scripts/fit_alpha.py", "raise SystemExit(1)\n")
    backend = RunnerBackend(piped)
    assert backend.poll(backend.submit()) == FAILED


def test_scoping_a_submission_still_runs_upstream(piped: Path) -> None:
    backend = RunnerBackend(piped)
    handle = backend.submit(["fit-beta"])
    assert set(backend.manifests(handle)) == {"fit-alpha", "fit-beta"}


def test_manifests_are_written_to_the_runner_store(piped: Path) -> None:
    RunnerBackend(piped).submit()
    stored = piped / ".specthis/runner/manifests/fit-alpha.json"
    assert json.loads(stored.read_text())["step"] == "fit-alpha"


# ------------------------------------------------- the step in the claim


def test_vouch_pins_the_step_and_rewiring_expires_it(piped: Path) -> None:
    """Realizing a spec means writing code *and* wiring it, so a judge
    claims about the step. Repointing a dep expires the judgment even
    though every file is untouched."""
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(piped))
    from specthis.check import Certification

    assert check_project(load_project(piped))["fit-alpha"].certification is Certification.CERTIFIED

    write(piped, "pipeline.toml", PIPELINE.replace(
        'deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json"]',
        'deps    = ["scripts/fit_alpha.py"]',
    ))
    report = check_project(load_project(piped))["fit-alpha"]
    assert report.certification is Certification.UNVOUCHED
    assert "step: fit-alpha rewired" in report.expired


def test_a_project_without_a_pipeline_carries_no_step_rows(root: Path) -> None:
    """Adding pipeline.toml is the only thing that brings step: rows into
    existence — otherwise every vouch would expire at once."""
    run_cli("vouch", "fit-alpha", "--as", "reviewer", "--path", str(root))
    from specthis.check import Certification, expected_inputs

    project = load_project(root)
    assert project.steps == {}
    assert not any(k.startswith("step:") for k in expected_inputs(project, project.entries["fit-alpha"], {}))
    assert check_project(project)["fit-alpha"].certification is Certification.CERTIFIED


def test_rewiring_also_stales_the_run(piped: Path) -> None:
    """The step sits on both axes: managers key on the command, so if
    specthis did not, a rewire would rerun while `check` said current."""
    run_cli("build", "--path", str(piped))
    assert realization(piped, "fit-alpha") is Realization.CURRENT
    rewired = PIPELINE.replace(
        f"{PY} scripts/fit_alpha.py", f"{PY} -X utf8 scripts/fit_alpha.py"
    )
    assert rewired != PIPELINE
    write(piped, "pipeline.toml", rewired)
    report = check_project(load_project(piped))["fit-alpha"]
    assert report.realization is Realization.STALE
    assert "~step:fit-alpha" in report.moved


# ------------------------------------------------- a project's own backend


def test_a_project_supplies_its_own_backend(piped: Path, monkeypatch) -> None:
    """An adapter for a real manager is project-specific glue, not a
    specthis feature: name it in the map and specthis imports it."""
    import sys
    import types

    from specthis.backends import DONE as _DONE
    from specthis.backends import resolve

    module = types.ModuleType("fakeproj_adapters")

    class Recording:
        def __init__(self, root, pipeline_path=None):
            self.root, self.name, self.calls = root, "fake", []

        def parse(self):
            return {}

        def submit(self, entries=None, force=False):
            self.calls.append(("submit", entries, force))
            return "h"

        def poll(self, handle):
            return _DONE

        def manifests(self, handle):
            return {}

    module.Recording = Recording
    monkeypatch.setitem(sys.modules, "fakeproj_adapters", module)
    write(piped, "specs/bindings.toml",
          (piped / "specs/bindings.toml").read_text()
          + '\n[backend]\nclass = "fakeproj_adapters:Recording"\n')

    backend = resolve(load_project(piped))
    assert isinstance(backend, Recording)
    result = run_cli("build", "--path", str(piped))
    assert result.exit_code == 0, result.output
    assert "0 claim(s) recorded from fake" in result.output


def test_a_bad_backend_path_is_a_clean_error(piped: Path) -> None:
    write(piped, "specs/bindings.toml",
          (piped / "specs/bindings.toml").read_text() + '\n[backend]\nclass = "nope"\n')
    result = run_cli("build", "--path", str(piped))
    assert result.exit_code != 0
    assert "module:ClassName" in result.output
