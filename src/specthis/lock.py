"""Content-hash lock: the certificate over the spec DAG.

Status: **stub**. The reference implementation maintains
``specs/_lock.json``, the certificate that spec, code, and outputs are
in sync. Each spec entry has two certified nodes:

**Implementation node** (spec -> code, certified by authorship). Records
that a specific script satisfies a specific spec contract:

- ``code``: the path of the script that implements the entry (the
  spec never carries this; it is registered here at certify time, a
  naming convention supplying the default).
- ``authorship_hash``: SHA-256 of (spec contract body + script body +
  package deps) at the moment the entry was certified.
- ``status``: ``ready`` when the live authorship hash matches;
  ``audit needed`` when it has drifted; ``unimplemented`` when no
  implementation node exists.
- ``depends_on``, ``author``, ``ts``: resolved deps and provenance.

**Artifact node** (code + inputs -> output, certified by execution).
Records that an output file was produced by that implementation from
known inputs:

- ``input_signature``: SHA-256 of (implementation authorship_hash +
  upstream artifact signatures + config). The remote cache
  (:mod:`specthis.cache`) is keyed by this.

The refresh orchestrator (:mod:`specthis.refresh`) compares the live
authorship hash against the certified one before re-running an entry; a
mismatch surfaces as ``audit needed`` and blocks the rerun. Because the
authorship hash covers the spec contract, a contract edit flips the
node to ``audit needed`` automatically -- no hand-maintained status.

Port plan:
- ``compute_authorship_hash(entry) -> str``
- ``compute_input_signature(entry) -> str``
- ``record(entry, code, author) -> None``   # register implementation node
- ``status(entry) -> Literal["ready", "audit needed", "unimplemented"]``
- ``clear(entry) -> None``
"""

from __future__ import annotations

from pathlib import Path


def record(entry: str, code: str, author: str, specs_dir: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.lock is not yet ported.")
