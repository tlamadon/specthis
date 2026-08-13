"""Read a pipeline: steps with declared inputs, outputs and edges.

specthis **reads** pipelines and never writes them (`specification.md`
§7). A step contributes exactly four things — ``id``, ``command``,
``deps``, ``outs`` — and everything else a backend supports (resources,
retries, matrices) is invisible here by design.

This module handles ``pipeline.toml``, the format the bundled runner
executes (§7.3). Other backends get their own reader returning the same
``Step`` objects; a reader is cheap and may be lenient about fields it
does not understand.

Pure: parsing and graph order only. No digests, no execution, no I/O
beyond reading the file.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

STEP_KEYS = {"command", "deps", "outs", "after"}


class PipelineError(Exception):
    """The pipeline file is unreadable or ill-formed. Never a guess."""


@dataclass(frozen=True)
class Step:
    """One unit of work, as the pipeline declares it.

    ``after`` is ordering no file expresses; ordinary edges are derived
    from ``deps``/``outs`` (:func:`predecessors`) so the same fact is
    never declared twice.
    """

    id: str
    command: str
    deps: tuple[str, ...] = ()
    outs: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


def _str_list(raw: object, where: str, key: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise PipelineError(f"{where}: `{key}` must be a list of strings")
    return tuple(raw)


def parse_pipeline(text: str, where: str = "pipeline.toml") -> dict[str, Step]:
    """Parse the document. Unknown keys are errors, never ignored — a
    typo must not silently drop a dependency."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PipelineError(f"{where}: {exc}") from exc
    if unknown := set(data) - {"steps"}:
        raise PipelineError(f"{where}: unknown top-level table(s) {sorted(unknown)}")

    steps: dict[str, Step] = {}
    for sid, table in data.get("steps", {}).items():
        at = f"{where}: [steps.{sid}]"
        if not isinstance(table, dict):
            raise PipelineError(f"{at}: must be a table")
        if unknown := set(table) - STEP_KEYS:
            raise PipelineError(f"{at}: unknown key(s) {sorted(unknown)}")
        command = table.get("command")
        if not isinstance(command, str) or not command.strip():
            raise PipelineError(f"{at}: `command` is required and must be a non-empty string")
        steps[sid] = Step(
            id=sid,
            command=command,
            deps=_str_list(table.get("deps"), at, "deps"),
            outs=_str_list(table.get("outs"), at, "outs"),
            after=_str_list(table.get("after"), at, "after"),
        )

    for step in steps.values():
        for a in step.after:
            if a not in steps:
                raise PipelineError(f"{where}: [steps.{step.id}] `after` names unknown step {a!r}")
    _duplicate_producers(steps, where)
    return steps


def _duplicate_producers(steps: dict[str, Step], where: str) -> None:
    """Two steps writing one path makes provenance unanswerable: which
    one produced the bytes on disk?"""
    owner: dict[str, str] = {}
    for step in sorted(steps.values(), key=lambda s: s.id):
        for out in step.outs:
            if out in owner:
                raise PipelineError(
                    f"{where}: `{out}` is declared by both {owner[out]!r} and {step.id!r}"
                )
            owner[out] = step.id


def load_pipeline(path: Path) -> dict[str, Step]:
    if not path.is_file():
        raise PipelineError(f"no pipeline at {path}")
    return parse_pipeline(path.read_text(encoding="utf-8"), where=path.name)


def producers(steps: dict[str, Step]) -> dict[str, str]:
    """Output path -> the step that declares it."""
    return {out: s.id for s in steps.values() for out in s.outs}


def predecessors(steps: dict[str, Step]) -> dict[str, set[str]]:
    """Steps that must precede each step.

    Derived from the files: a step follows every step whose ``outs`` its
    ``deps`` name, plus whatever ``after`` adds. Declaring an edge twice
    is how a pipeline drifts from itself.
    """
    by_out = producers(steps)
    return {
        s.id: {by_out[d] for d in s.deps if d in by_out and by_out[d] != s.id} | set(s.after)
        for s in steps.values()
    }


def topo_order(steps: dict[str, Step]) -> list[str]:
    """Step ids, upstream first."""
    try:
        return list(TopologicalSorter(predecessors(steps)).static_order())
    except CycleError as exc:
        raise PipelineError(f"pipeline cycle: {exc.args[1]}") from exc
