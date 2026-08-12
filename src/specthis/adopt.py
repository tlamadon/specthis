"""Countersign a manager's manifest into the run ledger.

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
"""

from __future__ import annotations

from dataclasses import dataclass

from . import hashing
from .check import expected_inputs
from .ledger import Run, read_runs, record_run
from .parse import Project


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
    entry = project.entries.get(entry_name)
    _require(entry is not None, f"no entry named `{entry_name}`")
    assert entry is not None

    outputs = manifest.get("outputs") or {}
    _require(bool(outputs), f"`{entry_name}`: manifest declares no outputs")
    declared = set(entry.outputs)
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
    entry = project.entries[entry_name]
    runs = read_runs(project.specs_dir)
    prior = runs.get(entry_name)

    inputs = expected_inputs(project, entry, runs)
    outputs = hashing.files_manifest(project.root, entry.outputs)
    out_sha = hashing.output_sha(project.root, entry.outputs)
    _require(out_sha is not None, f"`{entry_name}`: declared output(s) absent after the run")
    assert out_sha is not None

    run = Run(
        signature=hashing.signature(inputs),
        output=", ".join(entry.outputs),
        output_sha=out_sha,
        ran=manifest.get("finished_at") or manifest.get("started_at") or "",
        executor=str(manifest.get("executor") or "unknown"),
        inputs=inputs,
        outputs=outputs,
        duration_seconds=manifest.get("duration_seconds"),
    )
    record_run(project.specs_dir, entry_name, run)
    return Adopted(entry_name, run, prior is not None and prior.output_sha == out_sha)
