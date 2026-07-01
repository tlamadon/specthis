"""S3-backed compute cache for spec entries.

Status: **stub** — an explicitly deferred extension. git holds claims,
caches hold bytes, digests join them: the cache is keyed by an entry's
composed signature (the ``signature`` field of its ``runs.toml`` row),
so a collaborator whose check says *stale* can fetch the exact bytes
that signature certifies instead of recomputing. Nothing in the core
ledger depends on this module; deleting every cached byte changes no
answer ``specthis check`` gives.

Planned operations:

- ``push <entry>``: tar the entry's output directory and upload to
  ``s3://<bucket>/cache/<signature>/<entry>.tar.gz``.
- ``fetch <entry>``: download and unpack, then verify the unpacked
  output digest against the recorded ``output_sha``.
- ``has <entry>`` / ``list``.

Requires ``specthis[s3]`` extra (boto3) and AWS credentials available
in the standard chain (env, profile, instance role).
"""

from __future__ import annotations

from pathlib import Path


def push(entry: str, bucket: str, specs_dir: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.cache is not yet implemented.")


def fetch(entry: str, bucket: str, specs_dir: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.cache is not yet implemented.")
