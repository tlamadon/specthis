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


class Certification(Enum):
    """The vouch axis: a judgment about the *definition* (spec ↔ code
    pair), valid for any invocation, expiring only when a digest moves.
    Repair needs a mind."""

    UNIMPLEMENTED = "unimplemented"  # no code bound
    UNVOUCHED = "unvouched"  # code present, no vouch at the current pair
    REJECTED = "rejected"
    CERTIFIED = "certified"


class Realization(Enum):
    """The run axis: whether the memoized call is the call the current
    tree implies — a claim about *values*, independent of any vouch.
    Repair needs a machine. ``None`` for library entries (no run, no
    output: they exist only on the vouch axis)."""

    NEVER_RUN = "never-run"
    STALE = "stale"  # signature mismatch, or output bytes edited on disk
    CURRENT = "current"


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
    #: The two independent coordinates ``status`` is derived from.
    #: ``status`` flattens them (certification breaks win) for the
    #: legacy single-word surface; the axes carry the full state —
    #: e.g. an unvouched entry can also be stale, which ``status``
    #: alone cannot say.
    certification: Certification = Certification.CERTIFIED
    realization: Realization | None = None  # None for library entries
    #: Composition over each tree: every definition in the lineage
    #: certified / every call in the lineage current (libraries count
    #: as trivially realized). READY ≡ computable ∧ realized.
    computable: bool = True
    realized: bool = True
    moved: list[str] = field(default_factory=list)  # inputs that drifted since the run
    #: What moved since the vouch (AUDIT_NEEDED with a prior vouch
    #: only). Attribution needs the decomposed digests on the vouch
    #: row; rows from before those fields fall back to a bare
    #: "spec moved" / "code moved".
    expired: list[str] = field(default_factory=list)
    #: False when the claim stands but the declared output bytes are not
    #: on this disk (they live in the cache / on the machine that ran) —
    #: ready-but-fetchable, never a local break.
    materialized: bool = True


def code_present(project: Project, entry: Entry) -> bool:
    return bool(entry.binding.scripts) and all(
        (project.root / s).is_file() for s in entry.binding.scripts
    )


def is_library(entry: Entry) -> bool:
    return entry.spec.kind == "library"


def code_manifest(project: Project, entry: Entry) -> dict[str, str]:
    """The per-file form of ``code_sha``: script -> digest, plus the
    package blob under the ``"package"`` key.

    Recorded on vouches so that when the composed digest moves, the
    movement can be attributed (which script? the blob?) instead of
    only detected.
    """
    manifest = {
        s: hashing.file_sha(project.root / s) or hashing.MISSING
        for s in entry.binding.scripts
    }
    if project.package_globs:
        manifest["package"] = hashing.package_sha(
            project.root, project.package_globs, project.library_scripts
        )
    return manifest


def code_sha(project: Project, entry: Entry) -> str | None:
    """Manifest over the entry's scripts plus the package blob digest."""
    if not code_present(project, entry):
        return None
    return hashing.manifest_sha(code_manifest(project, entry).items())


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


def expired_since_vouch(
    project: Project, entry: Entry, v: Vouch, spec_sha_now: str, code_sha_now: str | None
) -> list[str]:
    """Attribute a vouch expiry: what moved between the vouched digests
    and now. Falls back to bare "spec moved" / "code moved" for rows
    written before the decomposed fields existed."""
    out: list[str] = []
    if v.spec_sha != spec_sha_now:
        fname = entry.spec.path.name
        if not v.spec_block_sha:
            out.append(f"spec: {fname} moved")
        elif v.spec_block_sha == entry.block_sha:
            out.append(f"spec: {fname} moved outside this entry's block")
        else:
            out.append(f"spec: this entry's block in {fname} moved")
    if v.code_sha != code_sha_now:
        if v.code_manifest:
            current = code_manifest(project, entry)
            moved = [
                "code: package blob moved" if k == "package" else f"code: {k} moved"
                for k in sorted(set(current) | set(v.code_manifest))
                if current.get(k) != v.code_manifest.get(k)
            ]
            out.extend(moved or ["code moved"])
        else:
            out.append("code moved")
    return out


def topo_order(project: Project) -> list[str]:
    """Entry names in dependency order (upstream first)."""
    sorter = TopologicalSorter({n: e.consumes for n, e in project.entries.items()})
    try:
        return list(sorter.static_order())
    except CycleError as exc:
        raise CheckError(f"consumes cycle: {exc.args[1]}") from exc


def _certify(
    project: Project, entry: Entry, v: Vouch | None, s: str, c: str | None
) -> tuple[Certification, list[str]]:
    """The vouch axis, with expiry attribution when a prior vouch exists."""
    if v is None or (v.spec_sha, v.code_sha) != (s, c):
        if c is None:
            return Certification.UNIMPLEMENTED, []
        expired = expired_since_vouch(project, entry, v, s, c) if v is not None else []
        return Certification.UNVOUCHED, expired
    if v.verdict == "rejected":
        return Certification.REJECTED, []
    return Certification.CERTIFIED, []


def _realize(
    project: Project, entry: Entry, r: Run | None, runs: dict[str, Run]
) -> tuple[Realization, list[str], bool]:
    """The run axis: (realization, moved attribution, materialized).

    Absent bytes are not edited bytes: the row is a claim, not an
    observation. The claim stands with the bytes elsewhere (fetch
    verifies on materialization); only present-but-different bytes
    are stale."""
    expected = expected_inputs(project, entry, runs)
    if r is None:
        return Realization.NEVER_RUN, [], True
    if r.signature != hashing.signature(expected):
        moved = sorted(
            k for k in set(expected) | set(r.inputs) if expected.get(k) != r.inputs.get(k)
        )
        return Realization.STALE, moved, True
    disk_sha = hashing.output_sha(project.root, entry.outputs)
    if disk_sha is None:
        return Realization.CURRENT, [], False
    if disk_sha != r.output_sha:
        return Realization.STALE, ["output (edited on disk)"], True
    return Realization.CURRENT, [], True


def check_project(
    project: Project,
    vouches: dict[str, Vouch] | None = None,
    runs: dict[str, Run] | None = None,
) -> dict[str, Report]:
    """Derive every entry's two coordinates, then the flattened status.

    Pure; reads ledgers once if not given. Both axes are computed
    unconditionally — the vouch axis never gates the run axis — so the
    joint state is always known. ``status`` flattens the pair the way
    the old single-pass gate did (certification breaks win, then
    staleness, then composition), keeping every legacy surface intact.
    """
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

        report.certification, expired = _certify(project, entry, v, s, c)
        certified = report.certification is Certification.CERTIFIED
        if is_library(entry):
            # The chain stops at code: no run, no output. A vouch at the
            # current digests is the whole claim.
            realization, moved, materialized = None, [], True
        else:
            realization, moved, materialized = _realize(project, entry, r, runs)
        report.realization = realization

        # Attribution and byte locality are run-axis facts: never gated
        # by the vouch axis. An unvouched entry still knows what moved
        # and where its bytes are.
        report.expired = expired
        report.moved = moved
        report.materialized = materialized

        report.computable = certified and all(reports[up].computable for up in entry.consumes)
        report.realized = (
            realization is None or realization is Realization.CURRENT
        ) and all(reports[up].realized for up in entry.consumes)

        if report.certification is Certification.UNIMPLEMENTED:
            report.status = Status.UNIMPLEMENTED
        elif report.certification is Certification.UNVOUCHED:
            report.status = Status.AUDIT_NEEDED
        elif report.certification is Certification.REJECTED:
            report.status = Status.REJECTED
        elif realization in (Realization.NEVER_RUN, Realization.STALE):
            report.status = Status.STALE
        elif any(reports[up].status is not Status.READY for up in entry.consumes):
            report.status = Status.UPSTREAM_UNVERIFIED
    return reports


def machine_repairable(r: Report) -> bool:
    """Membership in the machine queue: the realization is broken and a
    rerun is mechanically possible — code present, definition not
    rejected. Certification does not gate compute (trust gating lives
    in the vouch tree); rejection does — a machine must not realize a
    definition a mind refused."""
    return r.realization in (Realization.NEVER_RUN, Realization.STALE) and r.certification in (
        Certification.UNVOUCHED,
        Certification.CERTIFIED,
    )


def queues(reports: dict[str, Report]) -> tuple[list[Report], list[Report]]:
    """The two local queues: (mind, machine). One per tree — mind holds
    every definition break (unimplemented / unvouched / rejected),
    machine every mechanically repairable realization break. An entry
    can be in both: the mind audits while the machine reruns."""
    mind = [r for r in reports.values() if r.certification is not Certification.CERTIFIED]
    machine = [r for r in reports.values() if machine_repairable(r)]
    return mind, machine


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
