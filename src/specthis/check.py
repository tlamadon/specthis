"""Status derivation and the frontier report. Pure — zero writes.

``status()`` answers, per entry, whether its claims still hold and
what kind of repair a broken one needs: a mind (AUDIT_NEEDED /
REJECTED), a machine (STALE), or patience (UPSTREAM_UNVERIFIED).
Everything derives from content digests and the two ledgers; nothing
here consults mtime or writes a byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from graphlib import CycleError, TopologicalSorter

from . import hashing
from .ledger import Run, Vouch, read_runs, read_vouches
from .parse import Entry, Project


class Status(Enum):
    UNIMPLEMENTED = "unimplemented"
    AUDIT_NEEDED = "audit needed"
    REJECTED = "rejected"
    STALE = "stale"
    UPSTREAM_UNVERIFIED = "upstream-unverified"
    READY = "ready"


#: Broken for reasons local to the entry — itemized on the frontier.
LOCAL_BREAKS = {Status.UNIMPLEMENTED, Status.AUDIT_NEEDED, Status.REJECTED, Status.STALE}


class CheckError(Exception):
    pass


@dataclass
class Report:
    entry: str
    status: Status
    spec_sha: str
    code_sha: str | None  # None when code is missing
    vouch: Vouch | None
    run: Run | None
    moved: list[str] = field(default_factory=list)  # inputs that drifted since the run


def code_present(project: Project, entry: Entry) -> bool:
    return bool(entry.binding.scripts) and all(
        (project.root / s).is_file() for s in entry.binding.scripts
    )


def is_library(entry: Entry) -> bool:
    return entry.spec.kind == "library"


def code_sha(project: Project, entry: Entry) -> str | None:
    """Manifest over the entry's scripts plus the package blob digest."""
    if not code_present(project, entry):
        return None
    pairs = [(s, hashing.file_sha(project.root / s)) for s in entry.binding.scripts]
    if project.package_globs:
        pairs.append(
            (
                "package",
                hashing.package_sha(
                    project.root, project.package_globs, project.library_scripts
                ),
            )
        )
    return hashing.manifest_sha(pairs)  # type: ignore[arg-type]


def expected_inputs(project: Project, entry: Entry, runs: dict[str, Run]) -> dict[str, str]:
    """The ``[inputs]`` table a run of this entry would record right now.

    Script/workflow/package digests come from disk; each
    ``upstream:<entry>`` digest is the upstream's *recorded* output_sha
    (the claim, not the bytes) — an upstream that re-ran therefore
    changes this table, which is exactly the composed-signature fix.
    A library upstream has no output: its code manifest stands in, so
    a module edit makes its consumers stale (rerun with the new code).
    """
    inputs = hashing.files_manifest(
        project.root, [*entry.binding.scripts, *entry.binding.workflows]
    )
    if project.package_globs:
        inputs["package"] = hashing.package_sha(
            project.root, project.package_globs, project.library_scripts
        )
    for up in entry.consumes:
        up_entry = project.entries[up]
        if is_library(up_entry):
            inputs[f"upstream:{up}"] = code_sha(project, up_entry) or hashing.MISSING
        else:
            r = runs.get(up)
            inputs[f"upstream:{up}"] = r.output_sha if r else hashing.MISSING
    return inputs


def topo_order(project: Project) -> list[str]:
    """Entry names in dependency order (upstream first)."""
    sorter = TopologicalSorter({n: e.consumes for n, e in project.entries.items()})
    try:
        return list(sorter.static_order())
    except CycleError as exc:
        raise CheckError(f"consumes cycle: {exc.args[1]}") from exc


def check_project(
    project: Project,
    vouches: dict[str, Vouch] | None = None,
    runs: dict[str, Run] | None = None,
) -> dict[str, Report]:
    """Derive every entry's status. Pure; reads ledgers once if not given."""
    vouches = read_vouches(project.specs_dir) if vouches is None else vouches
    runs = read_runs(project.specs_dir) if runs is None else runs

    reports: dict[str, Report] = {}
    for name in topo_order(project):  # upstream first, so recursion is a lookup
        entry = project.entries[name]
        s = entry.spec.spec_sha
        c = code_sha(project, entry)
        v = vouches.get(name)
        r = runs.get(name)
        report = Report(entry=name, status=Status.READY, spec_sha=s, code_sha=c, vouch=v, run=r)
        reports[name] = report

        if v is None or (v.spec_sha, v.code_sha) != (s, c):
            report.status = Status.AUDIT_NEEDED if c is not None else Status.UNIMPLEMENTED
            continue
        if v.verdict == "rejected":
            report.status = Status.REJECTED
            continue
        if is_library(entry):
            # The chain stops at code: no run, no output. A vouch at the
            # current digests is the whole claim.
            if any(reports[up].status is not Status.READY for up in entry.consumes):
                report.status = Status.UPSTREAM_UNVERIFIED
            continue
        expected = expected_inputs(project, entry, runs)
        if r is None or r.signature != hashing.signature(expected):
            report.status = Status.STALE
            if r is not None:
                report.moved = sorted(
                    k
                    for k in set(expected) | set(r.inputs)
                    if expected.get(k) != r.inputs.get(k)
                )
            continue
        if hashing.output_sha(project.root, entry.outputs) != r.output_sha:
            report.status = Status.STALE
            report.moved = ["output (edited or deleted on disk)"]
            continue
        if any(reports[up].status is not Status.READY for up in entry.consumes):
            report.status = Status.UPSTREAM_UNVERIFIED
    return reports


def frontier(reports: dict[str, Report]) -> tuple[list[Report], int, int]:
    """Split reports into (itemized local breaks, waiting count, ready count).

    The frontier itemizes entries broken for their own reasons; entries
    that are merely downstream of a break are summarized as a count —
    fixing the frontier heals them for free. Never report only "the
    first broken link": this is a DAG.
    """
    local = [r for r in reports.values() if r.status in LOCAL_BREAKS]
    waiting = sum(1 for r in reports.values() if r.status is Status.UPSTREAM_UNVERIFIED)
    ready = sum(1 for r in reports.values() if r.status is Status.READY)
    return local, waiting, ready
