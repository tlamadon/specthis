"""Refresh orchestrator: re-runs stale entries respecting the lock.

Status: **stub**. The reference implementation:

1. Reads ``specs/_index.json`` (built by :mod:`specthis.export`) and
   ``specs/_lock.json`` (managed by :mod:`specthis.lock`).
2. For each entry, classifies state as one of: ``fresh``, ``stale``,
   ``unimplemented`` (no implementation node registered), or
   ``audit needed`` (the live authorship hash diverged from the
   certified one -- spec contract or code changed).
3. For ``stale`` entries, optionally fetches from the remote cache
   (:mod:`specthis.cache`, keyed by the artifact node's
   ``input_signature``) before falling back to a local rerun via the
   project's Makefile or a per-entry ``run:`` command.
4. After a successful rerun, optionally pushes the new artefacts to
   the S3 cache.

Port plan:
- ``classify(entry, index, lock) -> EntryState``
- ``plan(entries) -> RefreshPlan``
- ``execute(plan, dry_run) -> RefreshReport``
"""

from __future__ import annotations

from pathlib import Path


def run(specs_dir: Path, dry_run: bool = False) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.refresh is not yet ported.")
