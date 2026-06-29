"""Dashboard renderer: builds specs/specs.html + _index.json + _routing.json.

Status: **stub**. The reference implementation walks ``specs/*.md``,
parses each frontmatter + entry block, joins against the working tree
(script existence, output existence + top-level keys, export
artefacts, host-doc routing), and emits three artefacts:

- ``specs/specs.html`` — a single-file browsable dashboard of every
  spec, entry, and pairing.
- ``specs/_index.json`` — per-spec frontmatter + per-entry facts,
  consumed by :mod:`specthis.audit` and the auditor subagent.
- ``specs/_routing.json`` — per host-doc, per label section, the
  ``\\input{}`` / ``\\includegraphics{}`` lines found inside, plus
  ``\\sectionversion`` proximity flags.

Port plan:
- ``parse_spec(path) -> SpecFile``
- ``join_against_worktree(specs, project_root) -> IndexData``
- ``walk_host_docs(reports_dir) -> RoutingData``
- ``render_html(index, routing) -> str``
- ``write_artefacts(specs_dir, index, routing, html) -> None``
"""

from __future__ import annotations

from pathlib import Path


def render(specs_dir: Path, project_root: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.export is not yet ported.")
