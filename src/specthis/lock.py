"""Content-hash lock: the chain-of-links certificate over the spec DAG.

Status: **stub**. The reference implementation maintains
``specs/_lock.json``, the certificate that spec, code, and outputs are
in sync. The DAG has three kinds of node (``spec``, ``code``,
``artifact``) connected by up to three kinds of certified **link**, each
carrying one content hash:

**implements** (``spec -> code``, certified by authorship). Records that
a specific script satisfies a specific spec contract:

- ``code``: the path of the script that implements the entry (the
  spec never carries this; it is registered here at certify time, a
  naming convention supplying the default).
- ``authorship_hash``: SHA-256 of (spec body + code body, incl. its
  package deps) at the moment the entry was certified.
- ``depends_on``, ``author``, ``ts``: resolved deps and provenance.

**produces** (``code -> artifact``, certified by execution). Records
that an output file was produced by that code from known inputs:

- ``input_signature``: SHA-256 of (code + upstream artifact signatures
  + config). The remote cache (:mod:`specthis.cache`) is keyed by this.

**provides** (``spec -> artifact``, certified by content). For source /
external data that no code produces:

- ``content_hash``: SHA-256 of the artifact file itself.

An entry's derived ``status`` is ``ready`` when its ``implements`` link
authorship hash matches, ``audit needed`` when it has drifted (a broken
link), and ``unimplemented`` when no ``implements`` link exists.

The refresh orchestrator (:mod:`specthis.refresh`) compares the live
authorship hash against the certified one before re-running an entry; a
mismatch surfaces as ``audit needed`` and blocks the rerun. Because the
authorship hash covers the spec contract, a contract edit breaks the
``implements`` link automatically -- no hand-maintained status.

Port plan:
- ``compute_authorship_hash(entry) -> str``
- ``compute_input_signature(entry) -> str``
- ``record(entry, code, author) -> None``   # register the implements link
- ``status(entry) -> Literal["ready", "audit needed", "unimplemented"]``
- ``clear(entry) -> None``
"""

from __future__ import annotations

from pathlib import Path


def record(entry: str, code: str, author: str, specs_dir: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.lock is not yet ported.")
