"""Local dev server for specs.html with file-watch reload.

Status: **stub**. Serves ``specs/specs.html`` over HTTP, watches
``specs/*.md`` and the two ledgers for changes, and reruns the export
pipeline (:func:`specthis.export.render`) on each change before
triggering a browser reload via SSE. A viewing convenience only — the
ledger neither knows nor cares whether it runs.

Port plan:
- ``serve(host, port, specs_dir, project_root) -> None``
- ``_watch(paths) -> Iterator[Event]``
- ``_sse_handler(...) -> AsgiApp``

Requires ``specthis[serve]`` extra (uvicorn + starlette).
"""

from __future__ import annotations

from pathlib import Path


def serve(host: str, port: int, specs_dir: Path, project_root: Path) -> None:  # pragma: no cover - stub
    raise NotImplementedError("specthis.serve is not yet implemented.")
