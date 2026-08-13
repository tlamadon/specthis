"""The bundled runner against the compute-manager contract (§14)."""

import ast
import json
import sys
from pathlib import Path

import pytest

from specthis.pipeline import PipelineError, load_pipeline, predecessors, topo_order
from specthis.runner import RunnerError, manifests, run_pipeline

PY = sys.executable

PIPELINE = f"""\
[steps.clean]
command = '{PY} scripts/clean.py'
deps    = ["scripts/clean.py", "data/raw.txt"]
outs    = ["data/clean.txt"]

[steps.fit]
command = '{PY} scripts/fit.py'
deps    = ["scripts/fit.py", "data/clean.txt"]
outs    = ["results/fit.txt"]
"""

CLEAN_PY = """\
import pathlib
raw = pathlib.Path("data/raw.txt").read_text()
pathlib.Path("data/clean.txt").write_text(raw.strip().lower())
"""

FIT_PY = """\
import pathlib
pathlib.Path("results").mkdir(exist_ok=True)
clean = pathlib.Path("data/clean.txt").read_text()
pathlib.Path("results/fit.txt").write_text(f"n={len(clean)}")
"""


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    write(tmp_path, "pipeline.toml", PIPELINE)
    write(tmp_path, "scripts/clean.py", CLEAN_PY)
    write(tmp_path, "scripts/fit.py", FIT_PY)
    write(tmp_path, "data/raw.txt", "  HELLO  ")
    return tmp_path


def outcomes(results) -> dict[str, str]:
    return {r.step: r.outcome for r in results}


# ------------------------------------------------------------- the format


def test_edges_are_derived_from_files_not_declared_twice(proj: Path) -> None:
    steps = load_pipeline(proj / "pipeline.toml")
    assert predecessors(steps) == {"clean": set(), "fit": {"clean"}}
    assert topo_order(steps) == ["clean", "fit"]


def test_unknown_keys_are_errors(proj: Path) -> None:
    write(proj, "pipeline.toml", PIPELINE + '\n[steps.x]\ncommand = "true"\nresources = 4\n')
    with pytest.raises(PipelineError, match="unknown key"):
        load_pipeline(proj / "pipeline.toml")


def test_two_steps_cannot_declare_one_output(proj: Path) -> None:
    write(proj, "pipeline.toml", PIPELINE + '\n[steps.x]\ncommand = "true"\nouts = ["data/clean.txt"]\n')
    with pytest.raises(PipelineError, match="declared by both"):
        load_pipeline(proj / "pipeline.toml")


def test_cycles_are_errors(tmp_path: Path) -> None:
    write(tmp_path, "pipeline.toml",
          '[steps.a]\ncommand = "true"\ndeps = ["b.txt"]\nouts = ["a.txt"]\n'
          '[steps.b]\ncommand = "true"\ndeps = ["a.txt"]\nouts = ["b.txt"]\n')
    with pytest.raises(PipelineError, match="cycle"):
        topo_order(load_pipeline(tmp_path / "pipeline.toml"))


# ------------------------------------------------------------ the contract


def test_walks_in_dependency_order_and_produces_bytes(proj: Path) -> None:
    results = run_pipeline(proj)
    assert [r.step for r in results] == ["clean", "fit"]
    assert outcomes(results) == {"clean": "ran", "fit": "ran"}
    assert (proj / "results/fit.txt").read_text() == "n=5"


def test_second_walk_skips_everything(proj: Path) -> None:
    run_pipeline(proj)
    assert outcomes(run_pipeline(proj)) == {"clean": "skipped", "fit": "skipped"}


def test_decisions_are_content_keyed_not_mtime(proj: Path) -> None:
    run_pipeline(proj)
    p = proj / "data/raw.txt"
    p.write_text(p.read_text())  # touched, byte-identical
    assert outcomes(run_pipeline(proj)) == {"clean": "skipped", "fit": "skipped"}


def test_input_edit_reruns_the_step_and_its_dependents(proj: Path) -> None:
    run_pipeline(proj)
    write(proj, "data/raw.txt", "  GOODBYE  ")
    assert outcomes(run_pipeline(proj)) == {"clean": "ran", "fit": "ran"}
    assert (proj / "results/fit.txt").read_text() == "n=7"


def test_a_rerun_reproducing_identical_bytes_stops_the_cascade(proj: Path) -> None:
    """The cascade grows or stops dead — downstream keys on upstream
    *bytes*, not on the fact that upstream ran."""
    run_pipeline(proj)
    write(proj, "scripts/clean.py", CLEAN_PY + "# a comment changes nothing\n")
    assert outcomes(run_pipeline(proj)) == {"clean": "ran", "fit": "skipped"}


def test_edited_output_is_rebuilt(proj: Path) -> None:
    run_pipeline(proj)
    write(proj, "data/clean.txt", "tampered")
    assert outcomes(run_pipeline(proj))["clean"] == "ran"


def test_failure_blocks_dependents_and_writes_no_lock_entry(proj: Path) -> None:
    write(proj, "scripts/clean.py", "raise SystemExit(3)\n")
    results = run_pipeline(proj)
    assert outcomes(results) == {"clean": "failed", "fit": "blocked"}
    lock = json.loads((proj / ".specthis/runner/lock.json").read_text()) if (
        proj / ".specthis/runner/lock.json"
    ).is_file() else {}
    assert "clean" not in lock, "a failed step must never be reusable"


def test_exit_zero_without_declared_outputs_is_an_error(proj: Path) -> None:
    write(proj, "scripts/clean.py", "pass\n")  # succeeds, writes nothing
    with pytest.raises(RunnerError, match="declared output"):
        run_pipeline(proj)


def test_only_scopes_the_walk_but_never_drops_upstream(proj: Path) -> None:
    results = run_pipeline(proj, only=["fit"])
    assert outcomes(results) == {"clean": "ran", "fit": "ran"}


def test_force_bypasses_the_lock(proj: Path) -> None:
    run_pipeline(proj)
    assert outcomes(run_pipeline(proj, only=["clean"], force=True))["clean"] == "ran"


# ------------------------------------------------------------- manifests


def test_manifest_records_inputs_as_used_and_outputs_with_digests(proj: Path) -> None:
    run_pipeline(proj)
    m = manifests(proj)["fit"]
    assert m["manifest_version"] == 1
    assert set(m["inputs"]) == {"scripts/fit.py", "data/clean.txt"}
    assert set(m["outputs"]) == {"results/fit.txt"}
    assert all(len(sha) == 64 for sha in m["outputs"].values())
    assert m["exit_code"] == 0 and m["executor"] == "specthis-runner"


def test_skipped_steps_report_the_digests_a_run_would_have(proj: Path) -> None:
    """Hits are invisible: the caller cannot tell skip from run."""
    first = {r.step: (r.inputs, r.outputs) for r in run_pipeline(proj)}
    second = {r.step: (r.inputs, r.outputs) for r in run_pipeline(proj)}
    assert first == second


# -------------------------------------------------------------- boundary


def test_runner_never_imports_the_notary() -> None:
    """`specthis never forks a process` stays true of the notary: the
    runner is a co-shipped tool, not part of it."""
    src = Path(__file__).parent.parent / "src/specthis/runner.py"
    tree = ast.parse(src.read_text())
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    assert not imported & {"check", "ledger", "parse", "hashing", "cache", "remote"}


def test_a_command_change_reruns_the_step(proj: Path) -> None:
    """Without this, specthis stales the entry while the runner reports a
    hit — the entry is stale forever and no build ever fixes it."""
    run_pipeline(proj)
    write(proj, "pipeline.toml", PIPELINE.replace(
        f"{PY} scripts/clean.py", f"{PY} -X utf8 scripts/clean.py"
    ))
    assert outcomes(run_pipeline(proj))["clean"] == "ran"


def test_a_legacy_lock_without_a_command_rebuilds_once(proj: Path) -> None:
    run_pipeline(proj)
    lock = proj / ".specthis/runner/lock.json"
    data = json.loads(lock.read_text())
    for entry in data.values():
        entry.pop("command", None)
    lock.write_text(json.dumps(data))
    assert outcomes(run_pipeline(proj))["clean"] == "ran"
    assert outcomes(run_pipeline(proj))["clean"] == "skipped"
