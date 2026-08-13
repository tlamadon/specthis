"""The bundled reference runner: walk the DAG, and nothing else.

The smallest thing that satisfies the compute-manager contract
(`specification.md` §14), for projects with no manager of their own. It
exists as much to prove the contract is implementable as to be used:
if this file needs specthis internals to satisfy it, the contract is
underspecified.

**Deliberately absent — do not add:** parallelism, resources, remote
execution, retries, scheduling, log capture policy. Wanting any of them
is the signal to point scripthut or DVC at the same ``deps``/``outs``
declarations. Every one of those, added here, is a step back toward the
half-executor whose removal motivated the delegation in the first place.

**Boundary.** This module imports the standard library and
:mod:`specthis.pipeline` — never ``check``, ``ledger``, ``parse`` or
``hashing``. *specthis never forks a process* stays true of the notary;
the package merely ships a separate tool that does. A test asserts it.

What it guarantees, in the contract's terms:

1. dependency order — topological, and a failed step skips its dependents
2. content-keyed decisions — digests only, never mtimes
3. a manifest per step — inputs as used, outputs with digests, exit code
4. failures are never reused — a failed step writes no lock entry
5. hits are invisible — a skipped step reports the same digests it would
   have produced
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .pipeline import Step, load_pipeline, predecessors, topo_order

MISSING = "MISSING"
STATE_DIR = ".specthis/runner"
MANIFEST_VERSION = 1


class RunnerError(Exception):
    pass


@dataclass
class StepResult:
    step: str
    outcome: str  # "ran" | "skipped" | "failed" | "blocked"
    manifest: dict | None = None
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    exit_code: int | None = None


def _file_sha(path: Path) -> str:
    """sha256 of a file's bytes, or ``MISSING``. Never mtime, never size."""
    if not path.is_file():
        return MISSING
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _table(root: Path, paths: tuple[str, ...]) -> dict[str, str]:
    return {p: _file_sha(root / p) for p in sorted(paths)}


def _read_lock(state: Path) -> dict:
    lock = state / "lock.json"
    if not lock.is_file():
        return {}
    try:
        return json.loads(lock.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunnerError(f"unreadable lock at {lock}: {exc}") from exc


def _write_lock(state: Path, lock: dict) -> None:
    state.mkdir(parents=True, exist_ok=True)
    (state / "lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _up_to_date(root: Path, step: Step, lock: dict, inputs: dict[str, str]) -> bool:
    """Skip only when the recorded work matches *and* its products are
    still on disk unchanged. Absent or edited outputs mean re-run: this
    runner has no store to restore them from.

    The **command** is part of the key. Without it, editing a command
    would leave the recorded work looking identical here while specthis
    stales the claim — the entry would be stale forever and no rebuild
    would ever fix it. Locks written before this field rebuild once.
    """
    prior = lock.get(step.id)
    if not prior or prior.get("command") != step.command:
        return False
    if prior.get("deps") != inputs:
        return False
    recorded = prior.get("outs", {})
    if set(recorded) != set(step.outs):
        return False
    return all(_file_sha(root / p) == sha for p, sha in recorded.items())


def _manifest(step: Step, inputs: dict, outputs: dict, code: int, t0: float, t1: float) -> dict:
    return {
        "manifest_version": MANIFEST_VERSION,
        "step": step.id,
        "command": step.command,
        "inputs": inputs,
        "outputs": outputs,
        "exit_code": code,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t0)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t1)),
        "duration_seconds": round(t1 - t0, 3),
        "executor": "specthis-runner",
    }


def run_pipeline(
    root: Path,
    pipeline_path: Path | None = None,
    only: list[str] | None = None,
    force: bool = False,
    state_dir: str = STATE_DIR,
) -> list[StepResult]:
    """Bring the pipeline up to date and return one result per step.

    ``only`` scopes the walk to the named steps and everything they
    depend on — never less, since running a step over stale inputs would
    record a claim about bytes nobody vouched for. ``force`` bypasses the
    lock for the scoped steps (the integrity repair path, §10.3).
    """
    root = Path(root)
    steps = load_pipeline(pipeline_path or root / "pipeline.toml")
    state = root / state_dir
    lock = _read_lock(state)
    preds = predecessors(steps)

    wanted = set(steps)
    if only is not None:
        missing = sorted(set(only) - set(steps))
        if missing:
            raise RunnerError(f"no such step(s): {', '.join(missing)}")
        wanted, frontier = set(), list(only)
        while frontier:  # close over dependencies: upstream first, always
            sid = frontier.pop()
            if sid not in wanted:
                wanted.add(sid)
                frontier.extend(preds[sid])

    forced = set(only or ()) if force else set()
    results: list[StepResult] = []
    blocked: set[str] = set()

    for sid in topo_order(steps):
        if sid not in wanted:
            continue
        step = steps[sid]
        if preds[sid] & blocked:
            blocked.add(sid)
            results.append(StepResult(sid, "blocked"))
            continue

        inputs = _table(root, step.deps)
        if sid not in forced and _up_to_date(root, step, lock, inputs):
            outputs = lock[sid]["outs"]
            results.append(
                StepResult(sid, "skipped", None, inputs, outputs, 0)
            )
            continue

        t0 = time.time()
        proc = subprocess.run(step.command, shell=True, cwd=root)
        t1 = time.time()

        if proc.returncode != 0:
            blocked.add(sid)
            results.append(
                StepResult(
                    sid, "failed",
                    _manifest(step, inputs, {}, proc.returncode, t0, t1),
                    inputs, {}, proc.returncode,
                )
            )
            continue

        outputs = _table(root, step.outs)
        if absent := sorted(p for p, sha in outputs.items() if sha == MISSING):
            blocked.add(sid)
            results.append(
                StepResult(
                    sid, "failed",
                    _manifest(step, inputs, outputs, 0, t0, t1),
                    inputs, outputs, 0,
                )
            )
            raise RunnerError(
                f"`{sid}` exited 0 but declared output(s) are absent: {', '.join(absent)}"
            )

        lock[sid] = {"command": step.command, "deps": inputs, "outs": outputs}
        _write_lock(state, lock)  # after each step: an interrupt loses no work
        results.append(
            StepResult(sid, "ran", _manifest(step, inputs, outputs, 0, t0, t1), inputs, outputs, 0)
        )

    _write_manifests(state, results)
    return results


def _write_manifests(state: Path, results: list[StepResult]) -> None:
    out = state / "manifests"
    out.mkdir(parents=True, exist_ok=True)
    for r in results:
        if r.manifest is not None:
            (out / f"{r.step}.json").write_text(
                json.dumps(r.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )


def manifests(root: Path, state_dir: str = STATE_DIR) -> dict[str, dict]:
    """Every manifest this runner has written, by step id — the ``up``
    half of the seam (§7.2)."""
    out = (Path(root) / state_dir / "manifests")
    if not out.is_dir():
        return {}
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.json"))
    }
