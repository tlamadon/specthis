"""Dashboard renderer: builds specs/specs.html + _index.json + _routing.json.

Status: **stub**. The dashboards are *regenerated views*, never
sources of truth: they join the parsed specs (:mod:`specthis.parse`),
the derived statuses (:mod:`specthis.check`), and host-doc routing
into browsable artefacts. ``specthis check`` never reads them, and
nothing in them is hand-edited:

- ``specs/specs.html`` — a single-file browsable dashboard of every
  spec and entry with its derived status.
- ``specs/_index.json`` — per-spec frontmatter + per-entry facts
  (status, digests, outputs), for agents that want a queryable view.
- ``specs/_routing.json`` — per host-doc, per label section, the
  ``\\input{}`` / ``\\includegraphics{}`` lines found inside.

Port plan:
- ``render_html(reports, routing) -> str``
- ``walk_host_docs(reports_dir) -> RoutingData``
- ``write_artefacts(specs_dir, ...) -> None``
"""

from __future__ import annotations

from pathlib import Path


def render(specs_dir: Path, project_root: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.export is not yet implemented.")
