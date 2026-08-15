"""Countersign a manager's manifest into the run ledger — and answer back.

A manifest is an *unsigned factual report* from a machine: these input
digests, through this command, produced these output digests. Adopting
it is the notary act (`specification.md` §8.3) — verify, then record.

What verification can and cannot do is worth stating plainly, because
the earlier documents overstated it. Rehashing proves **transcription**:
the manifest's digests are digests of content specthis can see. It does
not prove **derivation** — that those outputs came from that code on
those inputs — because establishing that means re-running, which needs
the capability specthis lacks. Adoption catches a garbled or mismatched
manifest; it does not make the runner trustworthy.

Fail closed: a manifest that disagrees with the bytes on disk is
refused, never recorded with a warning.

Adoption also has a **return path** (:func:`publish`, §7.8). Recording a
claim and telling the manager nothing is what let ``check`` and ``build``
disagree permanently about the same entry; the adopted set is the ledger
projected into the manager's vocabulary, republished whenever a verb
writes ``runs.toml``.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import hashing, seam
from .check import (
    Realization,
    Report,
    check_project,
    expected_inputs,
    instance_inputs,
    sibling_keys,
)
from .ledger import Run, read_runs, record_run
from .instances import resolve_key
from .parse import Project
from .pipeline import producers


class AdoptError(Exception):
    """The manifest and the content disagree — nothing is recorded."""


@dataclass
class Adopted:
    entry: str
    run: Run
    reproduced: bool  # the outputs are byte-identical to the prior claim


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise AdoptError(msg)


def verify(project: Project, entry_name: str, manifest: dict) -> None:
    """Check a manifest against the project and the bytes on disk."""
    _require(
        manifest.get("manifest_version") == 1,
        f"`{entry_name}`: unknown manifest_version {manifest.get('manifest_version')!r}",
    )
    _require(manifest.get("exit_code") == 0, f"`{entry_name}`: manifest reports a failed step")
    try:
        entry, inst = resolve_key(project, entry_name)
    except KeyError:
        raise AdoptError(f"no entry or instance named `{entry_name}`") from None

    outputs = manifest.get("outputs") or {}
    _require(bool(outputs), f"`{entry_name}`: manifest declares no outputs")
    declared = set(inst.outputs if inst else entry.outputs)
    _require(
        declared <= set(outputs),
        f"`{entry_name}`: manifest is missing declared output(s) "
        f"{', '.join(sorted(declared - set(outputs)))}",
    )

    # Transcription, not derivation: every digest the manifest asserts
    # must be a digest of content on this disk.
    for path, sha in sorted({**(manifest.get("inputs") or {}), **outputs}.items()):
        actual = hashing.file_sha(project.root / path)
        _require(actual is not None, f"`{entry_name}`: manifest names an absent file {path}")
        _require(actual == sha, f"`{entry_name}`: {path} does not hash to the manifest's digest")


def adopt_manifest(project: Project, entry_name: str, manifest: dict) -> Adopted:
    """Verify a manifest and record the derived claim it supports.

    The recorded inputs are **specthis's** table, not the manifest's:
    a manager hashes the files its pipeline declares, while the ledger
    pins what the entry's own claim covers (upstream artefacts by their
    recorded digest, the package blob). Verification above is what ties
    the two together — every path they share must agree.
    """
    verify(project, entry_name, manifest)
    entry, inst = resolve_key(project, entry_name)
    runs = read_runs(project.specs_dir)
    prior = runs.get(entry_name)

    paths = list(inst.outputs if inst else entry.outputs)
    if inst is None:
        inputs = expected_inputs(project, entry, runs)
    else:
        inputs = instance_inputs(project, entry, inst, runs,
                                 sibling_keys(project, entry, inst))
    outputs = hashing.files_manifest(project.root, paths)
    out_sha = hashing.output_sha(project.root, paths)
    _require(out_sha is not None, f"`{entry_name}`: declared output(s) absent after the run")
    assert out_sha is not None

    run = Run(
        signature=hashing.signature(inputs),
        output=", ".join(paths),
        output_sha=out_sha,
        ran=manifest.get("finished_at") or manifest.get("started_at") or "",
        executor=str(manifest.get("executor") or "unknown"),
        inputs=inputs,
        outputs=outputs,
        duration_seconds=manifest.get("duration_seconds"),
    )
    record_run(project.specs_dir, entry_name, run)
    return Adopted(entry_name, run, prior is not None and prior.output_sha == out_sha)


# ------------------------------------------------------- the return path


def step_of(project: Project, key: str) -> str | None:
    """The pipeline step whose bytes a ledger key claims, or ``None``.

    The seam runs on step ids and the ledger on entry keys, so every
    bridge between them goes through here. **Identity comes from the
    output path** (§15.3): a template's step ids are whatever the
    backend called them, and matching an instance against the ``{prop}``
    pattern is the only resolution that survives that. An ordinary entry
    is looked up by name first, because that is the correspondence lint
    enforces (§7.4) and the one ``check`` itself uses — falling back to
    whichever step declares its outputs.

    ``None`` for library and source entries, which have no step, and for
    an entry whose bytes no step produces (lint's business, not ours).
    """
    entry, inst = resolve_key(project, key)
    if inst is not None:
        return inst.step or None
    if key in project.steps:
        return key
    by_out = producers(project.steps)
    return next((by_out[out] for out in entry.outputs if out in by_out), None)


def _accounted_for(report: Report) -> bool:
    """Does the ledger already answer for this key's bytes?

    The **run axis only**. Adoption is a machine-currency claim and must
    never imply a mind has judged anything, so an unvouched entry whose
    bytes are current is still accounted for — telling a manager to
    re-run it would not produce a vouch, only a bill.

    ``materialized`` is the other half: a claim can stand while its bytes
    live on the machine that made them (§10.3), and a manager cannot skip
    work whose products are not here.
    """
    return report.realization is Realization.CURRENT and report.materialized


def adopted_steps(
    project: Project, reports: dict[str, Report] | None = None
) -> dict[str, dict]:
    """The adopted set: every step whose bytes the ledger accounts for.

    Pure — derives the whole document from the ledger, the pipeline and
    the bytes on disk, so it is a projection rather than state that can
    drift. A step is published only when *every* key claiming it is
    current (one command can serve many entries) and every path it
    declares is on this disk: a partly-adopted step is not a satisfied
    one, and recording an absent file's digest would let a manager skip
    work whose output does not exist.

    Propagation is deliberately not consulted. A step whose upstream is
    stale still gets published, because the manager re-runs that upstream
    and the resulting digests no longer match this record — the digest
    comparison is what makes the answer safe, not our opinion about it.
    """
    reports = check_project(project) if reports is None else reports

    claimed: dict[str, list[str]] = {}
    for key in sorted(reports):
        sid = step_of(project, key)
        if sid is not None and sid in project.steps:
            claimed.setdefault(sid, []).append(key)

    out: dict[str, dict] = {}
    for sid, keys in sorted(claimed.items()):
        if not all(_accounted_for(reports[k]) for k in keys):
            continue
        step = project.steps[sid]
        deps = hashing.files_manifest(project.root, step.deps)
        outs = hashing.files_manifest(project.root, step.outs)
        if not outs or hashing.MISSING in {*deps.values(), *outs.values()}:
            continue
        out[sid] = {"entries": keys, "command": step.command, "deps": deps, "outs": outs}
    return out


def publish(project: Project, reports: dict[str, Report] | None = None) -> dict[str, dict]:
    """Write the adopted set and return it. The one writer of that file.

    No pipeline, no seam: a project without one has no manager to answer
    and gets no document — unless a stale one is lying there, which is
    emptied rather than left to be believed.

    Concurrency errs in the safe direction. A claim recorded by another
    process between this projection's ledger read and its write is simply
    absent from the document, which costs a re-run — never a wrong skip,
    since a step is published only against digests read here. ``build``
    republishes before every handoff, so the miss does not persist.
    """
    steps = adopted_steps(project, reports)
    if project.steps or (project.root / seam.DOCUMENT).is_file():
        seam.write_adopted(project.root, steps)
    return steps
