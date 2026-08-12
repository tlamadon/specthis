"""Do the spec, the map and the pipeline describe the same graph?

The pipeline is authored, not generated (`specification.md` §7), so
**lint — not construction — is what keeps the three artifacts
corresponding.** It replaces a compiler, and must therefore be complete:
anything a generator would have made unrepresentable has to be caught
here instead.

Pure: reads the loaded project, returns problems, changes nothing.
Silent when a project has no ``pipeline.toml`` — there is no
correspondence to check, and inventing one would fail every project that
has not adopted a pipeline yet.
"""

from __future__ import annotations

from .check import is_library
from .parse import Entry, Problem, Project

PIPELINE = "pipeline.toml"


def _output_paths(project: Project, entry: Entry) -> list[str]:
    """The physical paths this entry claims to produce.

    Today's format keeps them in the spec (``Output:``); the target
    moves them to ``map.produces`` (§4). Reading through this one
    accessor is what will make that migration a single edit.
    """
    return list(entry.outputs)


def correspondence_problems(project: Project) -> list[Problem]:
    """Every disagreement between spec, map and pipeline, all at once."""
    if not project.steps:
        return []

    problems: list[Problem] = []
    steps = project.steps
    entries = project.entries

    def bad(message: str) -> None:
        problems.append(Problem(PIPELINE, message))

    # --- spec <-> pipeline -------------------------------------------------
    for name, entry in sorted(entries.items()):
        if is_library(entry):
            if name in steps:
                bad(f"{PIPELINE}: `{name}` is a library entry and must have no step (§7.4)")
            continue
        if name not in steps:
            bad(f"{PIPELINE}: no step for entry `{name}` — declared but never built")

    for sid in sorted(steps):
        if sid not in entries:
            bad(f"{PIPELINE}: step `{sid}` matches no entry — nothing claims its bytes")

    # --- map <-> pipeline --------------------------------------------------
    for name, entry in sorted(entries.items()):
        step = steps.get(name)
        if step is None:
            continue
        declared = set(step.outs)
        for out in _output_paths(project, entry):
            if out not in declared:
                bad(
                    f"{PIPELINE}: `{name}` declares output `{out}` that step `{name}` "
                    "does not produce"
                )
        for script in entry.binding.scripts:
            if script not in step.deps:
                bad(
                    f"{PIPELINE}: `{script}` is judged code for `{name}` but is not among "
                    f"step `{name}`'s deps — an edit would expire the vouch without "
                    "staling the run"
                )

    # --- spec edges <-> pipeline edges -------------------------------------
    produced_by = {
        out: name
        for name, entry in entries.items()
        for out in _output_paths(project, entry)
        if not is_library(entry)
    }
    for name, entry in sorted(entries.items()):
        step = steps.get(name)
        if step is None:
            continue
        for up in entry.consumes:
            up_entry = entries.get(up)
            if up_entry is None or is_library(up_entry):
                continue  # library edges carry code, not artefacts (§7.6)
            wanted = set(_output_paths(project, up_entry))
            if wanted and not (wanted & set(step.deps)):
                bad(
                    f"{PIPELINE}: `{name}` consumes `{up}` but step `{name}` depends on none "
                    f"of its outputs ({', '.join(sorted(wanted))}) — the contract declares an "
                    "edge the pipeline does not build"
                )
        for dep in step.deps:
            owner = produced_by.get(dep)
            if owner and owner != name and owner not in entry.consumes:
                bad(
                    f"{PIPELINE}: step `{name}` depends on `{dep}`, produced by `{owner}`, "
                    f"but `{name}` does not consume `{owner}` — the pipeline builds an edge "
                    "the contract does not declare"
                )

    return problems


def correspondence_warnings(project: Project) -> list[Problem]:
    """Not wrong, but worth saying — attribution and coverage gaps."""
    if not project.steps:
        return []
    out: list[Problem] = []
    claimed = {
        p for name, e in project.entries.items() for p in _output_paths(project, e)
    }
    for sid, step in sorted(project.steps.items()):
        # A command that merely names hashed files has almost no room to
        # be wrong; flags are parameters nobody can attribute (§5.7).
        parts = step.command.split()
        if any(a.startswith("-") for a in parts[1:]):
            out.append(
                Problem(
                    PIPELINE,
                    f"{PIPELINE}: step `{sid}`'s command carries flags — a change moves "
                    "`step:` wholesale instead of naming a config file that moved; "
                    "put parameters in a file listed among deps",
                )
            )
        for o in step.outs:
            if o not in claimed:
                out.append(
                    Problem(
                        PIPELINE,
                        f"{PIPELINE}: step `{sid}` produces `{o}`, which no entry claims — "
                        "produced but anonymous, so nothing downstream can consume it",
                    )
                )
    return out
