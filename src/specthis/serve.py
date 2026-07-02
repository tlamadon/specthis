"""Local dev server for the specs dashboard, stdlib only.

Serves the rendered dashboard from memory (it writes nothing) and
re-renders when anything the view depends on changes: spec files, the
ledgers, bindings, scripts, workflow files, outputs, or the package
blob. The browser polls ``/__state`` and reloads when the token bumps.

A viewing convenience only — the ledger neither knows nor cares
whether it runs. Change detection uses a cheap ``stat`` scan (mtime +
size) purely to decide *when* to re-render; every status shown is
still derived from content digests by :mod:`specthis.check`.
"""

from __future__ import annotations

import html
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .export import render
from .parse import Project, SpecError, load_project_lenient

POLL_SECONDS = 1.0


def _watched_paths(root: Path, project: Project | None) -> list[Path]:
    """Everything the rendered view depends on."""
    paths = sorted((root / "specs").glob("*.md")) + sorted((root / "specs").glob("*.toml"))
    if project is not None:
        rel: set[str] = set()
        for entry in project.entries.values():
            rel.update(entry.binding.scripts)
            rel.update(entry.binding.workflows)
            rel.update(entry.outputs)
        rel.update(s.host_doc for s in project.specs if s.host_doc)
        paths += [root / r for r in sorted(rel)]
        for pattern in project.package_globs:
            paths += sorted(p for p in root.glob(pattern) if p.is_file())
    return paths


def _stat_fingerprint(paths: list[Path]) -> tuple:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(p), None, None))
    return tuple(out)


_ERROR_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>specthis — parse error</title></head>
<body style="font: 15px/1.6 -apple-system, sans-serif; max-width: 720px; margin: 40px auto;">
<h1 style="font-size:20px">specs/ does not parse right now</h1>
<pre style="background:#fff8f8; border:1px solid #ffd7d5; padding:14px; border-radius:8px;
white-space:pre-wrap">{message}</pre>
<p style="color:#57606a">Fix the file and this page will reload itself.</p>
<script>
setInterval(async () => {{
  try {{
    const s = await (await fetch('/__state', {{cache: 'no-store'}})).json();
    if (s.token !== {token}) location.reload();
  }} catch (e) {{}}
}}, 1000);
</script></body></html>
"""


class Dashboard:
    """Shared render state: refreshed by the watcher, read by the handler."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self.token = 0
        self.html = ""
        self._fingerprint: tuple | None = None
        self._project: Project | None = None
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> bool:
        """Re-render if any watched file moved. Returns True if it did."""
        fingerprint = _stat_fingerprint(_watched_paths(self.root, self._project))
        if not force and fingerprint == self._fingerprint:
            return False
        error = ""
        try:
            # Lenient: grammar problems render into the page; only a
            # missing specs/ directory falls through to the error page.
            project, problems = load_project_lenient(self.root)
            page, _index, _routing = render(project, problems)
            self._project = project
            # the watch list may have grown (new scripts/outputs) — re-stat it
            fingerprint = _stat_fingerprint(_watched_paths(self.root, project))
        except SpecError as exc:
            page = None
            self._project = None
            error = str(exc)
        with self._lock:
            self.token += 1
            self.html = (
                page
                if page is not None
                else _ERROR_PAGE.format(message=html.escape(error), token=self.token)
            )
            self._fingerprint = fingerprint
        return True

    def snapshot(self) -> tuple[int, str]:
        with self._lock:
            return self.token, self.html


def _make_handler(dashboard: Dashboard) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            token, page = dashboard.snapshot()
            if self.path in ("/", "/specs.html", "/index.html"):
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/__state":
                body = json.dumps({"token": token}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            pass  # keep the terminal quiet; the dashboard is the output

    return Handler


def serve(host: str, port: int, root: Path, poll_seconds: float = POLL_SECONDS) -> None:
    """Serve the dashboard until interrupted, re-rendering on change."""
    dashboard = Dashboard(root)
    httpd = ThreadingHTTPServer((host, port), _make_handler(dashboard))

    def watch() -> None:
        while True:
            time.sleep(poll_seconds)
            dashboard.refresh()

    threading.Thread(target=watch, daemon=True).start()
    actual_port = httpd.server_address[1]
    print(f"specthis dashboard at http://{host}:{actual_port}/  (ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
