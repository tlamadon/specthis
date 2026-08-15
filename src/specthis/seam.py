"""What crosses between the notary and a compute manager.

Two documents were always here: the pipeline goes down, manifests come
back up (`specification.md` §7.2). This module holds the third — the
**adopted set**, specthis's answer to the only question a manager ever
asks it: *which of these steps are already accounted for?*

Why it has to exist. ``adopt`` is how off-machine results enter a
project — it is the point of the architecture. Before this document, it
wrote the ledger and told the manager nothing: ``check`` read the ledger
and called the entry current, the manager consulted its own lock, found
no record (it never ran the step) and executed it again. The two
disagreed permanently, and where a step's command submits cluster jobs
the disagreement costs a queue, not a core.

Three properties are load-bearing:

- **A projection, not a second ledger.** Every field is derived from
  ``runs.toml``, the pipeline and the bytes on disk, so republishing an
  unchanged project rewrites identical bytes and deleting the file loses
  nothing. Two records that can drift apart is the bug this fixes; a
  cache that can be regenerated is not one.
- **Manager-agnostic.** specthis must not learn one manager's lock
  format, so it publishes its own vocabulary — step id, command, and the
  two digest tables — and any manager that reads JSON can consult it.
- **Evidence, never an order.** The digests are here so the manager can
  decide for itself. specthis never selects steps (§14 MUST 2): a record
  says "these bytes are accounted for, at these digests", and a manager
  that finds the digests moved must run the step anyway.

Pure: this module reads and writes one JSON file and compares
dictionaries. It imports nothing from specthis, so a manager — the
bundled runner included — can consult the seam without importing the
notary.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

#: Where the adopted set lives, relative to the project root. Derived
#: state: regenerate with ``specthis adopted``, and gitignore it.
DOCUMENT = ".specthis/adopted.json"

#: Bumped only for a change a reader cannot ignore. An unknown version
#: is an error, never a silent empty set — a manager that quietly
#: ignored the document would re-run every adopted step, which is
#: exactly the failure this file exists to prevent.
ADOPTED_VERSION = 1


class SeamError(Exception):
    """The adopted set is unreadable or speaks a version we do not."""


def read_adopted(root: Path, document: str = DOCUMENT) -> dict[str, dict]:
    """The adopted set, step id -> record. Empty when absent.

    Absent is not an error: a project that has adopted nothing has
    nothing to say, and every manager must work without this file.
    """
    path = Path(root) / document
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeamError(f"unreadable adopted set at {path}: {exc}") from exc
    version = data.get("adopted_version")
    if version != ADOPTED_VERSION:
        raise SeamError(
            f"{path}: adopted_version {version!r} is not {ADOPTED_VERSION} — "
            "regenerate it with `specthis adopted`"
        )
    steps = data.get("steps") or {}
    if not isinstance(steps, dict):
        raise SeamError(f"{path}: `steps` must be a table")
    return steps


def write_adopted(root: Path, steps: Mapping[str, dict], document: str = DOCUMENT) -> Path:
    """Publish the adopted set, atomically.

    ``adopt`` and ``build`` can run at once, and a manager may read
    while either writes; ``os.replace`` is what makes a reader see the
    old document or the new one and never half of either.
    """
    path = Path(root) / document
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"adopted_version": ADOPTED_VERSION, "steps": dict(sorted(steps.items()))},
        indent=2,
        sort_keys=True,
    ) + "\n"
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    return path


def satisfies(
    record: Mapping | None,
    command: str,
    deps: Mapping[str, str],
    outs: Sequence[str],
    digest: Callable[[str], str],
) -> bool:
    """Does this record account for a step as the pipeline declares it now?

    The shared decision procedure — the bundled runner asks it of both
    its own lock and the adopted set, and any manager may use it. Four
    things must hold, and each one is a bug somebody has already had:

    1. **The command matches.** Editing a command moves ``step:`` in the
       ledger, so specthis stales the entry; a manager keyed only on
       file digests would report a hit and the entry would be stale
       forever, with no rebuild that could fix it.
    2. **The dependency table matches exactly** — same paths, same
       digests. This is what keeps an adopted step from being pinned as
       permanently satisfied: touch a dep and the record stops applying.
    3. **The recorded outputs are the outputs the step declares**, so
       adding an out invalidates the record instead of being ignored.
    4. **Those outputs are still on disk with the recorded bytes.** A
       record is a claim about content; without this, an artefact edited
       or deleted by hand would be skipped over.
    """
    if not record or record.get("command") != command:
        return False
    if record.get("deps") != dict(deps):
        return False
    recorded = record.get("outs") or {}
    if not recorded or set(recorded) != set(outs):
        return False
    return all(digest(path) == sha for path, sha in sorted(recorded.items()))
