"""Certify-where-the-bytes-are: remote manifests and ledger adoption.

An intensive entry can run where its bytes should live (HPC scratch, a
collaborator's machine) while the git pen stays on the laptop. Two
halves, one per machine:

- ``certify`` runs wherever the repo checkout and the output bytes
  coexist — a scripthut task's last line, a slurm epilogue. It computes
  the entry's inputs table, signature, and output digest through the
  same code paths ``run`` uses (composition never leaves specthis),
  uploads the outputs tarball to the entry's cache key plus a small
  ``.manifest.json`` sidecar, and records the derived row in the
  *local clone's* runs.toml — the same claim ``run`` would write, never
  committed by the tool — so a downstream entry certified later in the
  same workflow composes its signature against the fresh digest. No
  git identity, no attested claim.

- ``adopt`` runs on the machine holding the git pen. It recomputes the
  expected signature locally and pulls the manifest at that exact cache
  key. The key is the integrity check: a drifted working tree (dirty,
  unpushed, wrong branch) composes a different signature and finds
  nothing, so a row can never be recorded against inputs that did not
  produce it. Bytes are never downloaded; materialization stays with
  the verified ``fetch``, on demand.

A wrong or forged manifest fails closed: at adoption (signature or
composition mismatch) or at ``fetch`` (byte digest mismatch). The trust
boundary is cache write access, exactly as it is for ``push``.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import hashing
from .cache import _key, _manifest_key, _store, _upload_archive
from .check import expected_inputs, is_library
from .ledger import Run, read_runs, record_run
from .parse import Entry, Project


class RemoteError(Exception):
    """A certification or adoption would record something untrue."""


@dataclass
class Manifest:
    """The claim metadata that travels instead of the bytes."""

    entry: str
    signature: str
    output_sha: str
    outputs: dict[str, dict]  # path -> {"sha256": ..., "size": ...}
    executor: str
    created: str  # ISO8601 UTC


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entry_and_inputs(project: Project, name: str) -> tuple[Entry, dict[str, str]]:
    """The same guards ``run`` applies before trusting an inputs table."""
    entry = project.entries[name]
    if is_library(entry):
        raise RemoteError(
            f"`{name}` is a library entry — the chain stops at code; "
            "there are no bytes to certify or adopt"
        )
    runs = read_runs(project.specs_dir)
    missing_up = [
        u for u in entry.consumes if u not in runs and not is_library(project.entries[u])
    ]
    if missing_up:
        raise RemoteError(
            f"`{name}` consumes entries with no recorded run: "
            f"{', '.join(missing_up)} — certify/adopt those first"
        )
    inputs = expected_inputs(project, entry, runs)
    missing_files = sorted(k for k, v in inputs.items() if v == hashing.MISSING)
    if missing_files:
        raise RemoteError(f"`{name}` has missing input files: {', '.join(missing_files)}")
    return entry, inputs


def certify(project: Project, name: str, executor: str = "remote") -> Manifest:
    """Certify this machine's bytes for the entry and upload them.

    Fail-closed ordering: every digest is computed and the store
    resolved before any upload; the tarball goes up before the manifest
    sidecar, so an interrupted certification leaves nothing adoptable
    at the final key.
    """
    entry, inputs = _entry_and_inputs(project, name)
    per_file = {rel: hashing.file_sha(project.root / rel) for rel in entry.outputs}
    absent = sorted(rel for rel, sha in per_file.items() if sha is None)
    if absent:
        raise RemoteError(
            f"`{name}` declared output(s) missing on this disk: {', '.join(absent)} "
            "— certify runs where the bytes are"
        )
    signature = hashing.signature(inputs)
    manifest = Manifest(
        entry=name,
        signature=signature,
        output_sha=hashing.composed_output_sha(
            [(rel, per_file[rel]) for rel in entry.outputs]  # type: ignore[misc]
        ),
        outputs={
            rel: {"sha256": per_file[rel], "size": (project.root / rel).stat().st_size}
            for rel in entry.outputs
        },
        executor=executor,
        created=_now(),
    )
    store = _store(project)  # raises before anything is uploaded
    _upload_archive(project, entry, _key(name, signature))
    with tempfile.TemporaryDirectory() as tmp:
        sidecar = Path(tmp) / "manifest.json"
        sidecar.write_text(json.dumps(vars(manifest), indent=2), encoding="utf-8")
        store.put(_manifest_key(name, signature), sidecar)
    record_run(
        project.specs_dir,
        name,
        Run(
            signature=signature,
            output=", ".join(entry.outputs),
            output_sha=manifest.output_sha,
            ran=manifest.created,
            executor=executor,
            inputs=inputs,
        ),
    )
    return manifest


def adopt(project: Project, name: str) -> Run:
    """Record the runs.toml row for a remotely-certified entry.

    Never downloads the bytes and never touches an attested claim.
    """
    entry, inputs = _entry_and_inputs(project, name)
    signature = hashing.signature(inputs)
    store = _store(project)
    with tempfile.TemporaryDirectory() as tmp:
        sidecar = Path(tmp) / "manifest.json"
        if not store.get(_manifest_key(name, signature), sidecar):
            raise RemoteError(
                f"no remote claim for `{name}` at signature {signature[:12]}… — "
                "nothing was certified for these exact inputs, or the working "
                "tree drifted from the one that ran (dirty tree? unpushed edits? "
                "upstream entries not adopted yet?)"
            )
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RemoteError(f"remote manifest for `{name}` is not valid JSON") from exc

    if data.get("entry") != name or data.get("signature") != signature:
        raise RemoteError(
            f"remote manifest does not match `{name}` at this signature — refusing"
        )
    recorded = data.get("outputs") or {}
    if sorted(recorded) != sorted(entry.outputs):
        raise RemoteError(
            f"remote manifest certifies different outputs than `{name}` declares "
            f"({', '.join(sorted(recorded)) or 'none'} vs {', '.join(entry.outputs)}) — refusing"
        )
    pairs = [(rel, str(recorded[rel].get("sha256", ""))) for rel in entry.outputs]
    if hashing.composed_output_sha(pairs) != data.get("output_sha"):
        raise RemoteError(
            "remote manifest's composed output digest does not match its own "
            "per-file digests — refusing"
        )
    run = Run(
        signature=signature,
        output=", ".join(entry.outputs),
        output_sha=str(data["output_sha"]),
        ran=str(data.get("created") or _now()),
        executor=str(data.get("executor") or "remote"),
        inputs=inputs,
    )
    record_run(project.specs_dir, name, run)
    return run
