"""The seam to a compute manager: four operations, two documents.

`specification.md` §7.2. A backend is anything that can be wrapped into

    parse(pipeline_file) -> [ {id, command, deps, outs, after} ]
    submit(entries=None, force=False) -> handle
    poll(handle)                      -> running | done | failed
    manifests(handle)                 -> { entry: manifest }

and that honours the contract in §14 — dependency order, content-keyed
decisions, a manifest per step, failures never reused.

specthis never selects steps: ``submit`` with no ``entries`` means
*bring the whole pipeline up to date*, and the manager decides what
actually executes. ``entries`` scopes a repair; ``force`` bypasses the
manager's cache, which is the integrity path (§10.3) — the one case
where specthis asks for specific work.

Only the bundled runner is implemented here. A scripthut or DVC backend
is the same four methods over their own plan format and manifest
endpoint; nothing above this module knows which one it is talking to.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .pipeline import Step, load_pipeline
from .runner import StepResult, manifests as runner_manifests, run_pipeline

RUNNING, DONE, FAILED = "running", "done", "failed"


class BackendError(Exception):
    pass


class Backend(Protocol):
    """What specthis needs from a compute manager. Nothing more."""

    name: str

    def parse(self) -> dict[str, Step]: ...

    def submit(self, entries: list[str] | None = None, force: bool = False) -> str: ...

    def poll(self, handle: str) -> str: ...

    def manifests(self, handle: str) -> dict[str, dict]: ...


@dataclass
class RunnerBackend:
    """The bundled runner (§7.3) behind the four operations.

    Synchronous: ``submit`` runs the walk and ``poll`` reports what it
    found, so the handle is only a receipt. An asynchronous backend —
    a cluster — returns a real handle and ``poll`` reports progress; the
    caller's loop is identical either way.
    """

    root: Path
    pipeline_path: Path | None = None
    name: str = "specthis-runner"

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self._results: dict[str, list[StepResult]] = {}

    def parse(self) -> dict[str, Step]:
        return load_pipeline(self.pipeline_path or self.root / "pipeline.toml")

    def submit(self, entries: list[str] | None = None, force: bool = False) -> str:
        handle = f"local-{len(self._results)}"
        self._results[handle] = run_pipeline(
            self.root, self.pipeline_path, only=entries, force=force
        )
        return handle

    def poll(self, handle: str) -> str:
        results = self._results.get(handle)
        if results is None:
            raise BackendError(f"unknown handle {handle!r}")
        return FAILED if any(r.outcome in ("failed", "blocked") for r in results) else DONE

    def manifests(self, handle: str) -> dict[str, dict]:
        """Every manifest for steps this submission touched.

        Skipped steps have no fresh manifest — a cache hit writes no new
        record — so their last one is served from the runner's store.
        The caller cannot tell hit from run, which is §14 MUST 5.
        """
        results = self._results.get(handle)
        if results is None:
            raise BackendError(f"unknown handle {handle!r}")
        stored = runner_manifests(self.root)
        out: dict[str, dict] = {}
        for r in results:
            if r.manifest is not None:
                out[r.step] = r.manifest
            elif r.outcome == "skipped" and r.step in stored:
                out[r.step] = stored[r.step]
        return out
