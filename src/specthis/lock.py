"""Content-hash lock for spec entries.

Status: **stub**. The reference implementation maintains
``specs/_lock.json`` keyed by entry name, recording:

- ``inputs_certified``: SHA-256 of (spec body + script body + workflow
  files) at the moment the entry was certified ``script ready``.
- ``depends_on``: the entry's resolved dependency list at certification
  time.
- ``author``, ``ts``: who certified, when.

The refresh orchestrator (:mod:`specthis.refresh`) compares the live
hash against ``inputs_certified`` before re-running an entry; a
mismatch surfaces as ``spec audit needed`` and blocks the rerun.

Port plan:
- ``compute_inputs_hash(entry) -> str``
- ``record_inputs(entry, author) -> None``
- ``status(entry) -> Literal["certified", "drifted", "uncertified"]``
- ``clear(entry) -> None``
"""

from __future__ import annotations

from pathlib import Path


def record_inputs(entry: str, author: str, specs_dir: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.lock is not yet ported.")
