"""S3-backed compute cache for spec entries.

Status: **stub**. The reference implementation provides four
operations keyed by an entry's ``inputs_certified`` hash:

- ``push <entry>``: tar the entry's ``results/<entry>/`` directory and
  upload to ``s3://<bucket>/cache/<input_sig>/<entry>.tar.gz``.
- ``fetch <entry>``: download and unpack into ``results/<entry>/``.
- ``has <entry>``: HEAD-check S3 for the artefact.
- ``list``: list cached entries with their input signatures.

Requires ``specthis[s3]`` extra (boto3) and AWS credentials available
in the standard chain (env, profile, instance role).
"""

from __future__ import annotations

from pathlib import Path


def push(entry: str, bucket: str, specs_dir: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.cache is not yet ported.")


def fetch(entry: str, bucket: str, specs_dir: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.cache is not yet ported.")
