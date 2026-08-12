"""Code identity as a file, so a manager can hash it (spec §6).

**Most projects need none.** A step lists its code among its
dependencies anyway, so those digests are already in the manager's key
and in the manifest — which is what joins a run to a vouch, directly on
``(path, sha)``.

A certificate earns its place in exactly one case: ``[package] globs``.
A glob has no stable file list, so it cannot be a step dependency; the
only way its composed digest enters a manager's key is as a file.

**Keyed content is code identity only** — no verdict, no ``spec_sha``,
no timestamp. If any entered, vouching something would rebuild it and
rewording prose would rebuild it, destroying the property that a
clarification costs zero compute.

**Serialization is deterministic**: sorted keys, fixed indent, trailing
newline. Regenerating unchanged code must produce a byte-identical file,
or every regeneration would bust every cache — the mechanism would
defeat itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from .check import code_manifest
from .parse import Entry, Project

CERTIFICATE_VERSION = 1
CERT_DIR = "certificates"


def content(project: Project, entry: Entry) -> dict:
    """The certificate document for one entry."""
    manifest = code_manifest(project, entry)
    doc: dict = {
        "certificate_version": CERTIFICATE_VERSION,
        "entry": entry.name,
        "code": {k: v for k, v in sorted(manifest.items()) if k != "package"},
    }
    if "package" in manifest:
        doc["package"] = manifest["package"]
    return doc


def render(doc: dict) -> str:
    """Byte-identical for identical code. Nothing here may vary run to run."""
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def path_for(project: Project, entry_name: str) -> Path:
    return project.specs_dir / CERT_DIR / f"{entry_name}.json"


def write_all(project: Project) -> list[Path]:
    """Emit a certificate per entry that has code bound.

    Returns the paths written. Rewriting an unchanged certificate leaves
    the bytes alone, so a regeneration never stales anything.
    """
    out: list[Path] = []
    for name, entry in sorted(project.entries.items()):
        if not entry.binding.scripts:
            continue
        target = path_for(project, name)
        text = render(content(project, entry))
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        out.append(target)
    return out
