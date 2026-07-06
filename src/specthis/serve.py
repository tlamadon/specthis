"""Local dev server for the specs dashboard, stdlib only.

Serves the rendered dashboard from memory (it writes nothing into the
project tree) and re-renders when anything the view depends on
changes: spec files, the ledgers, bindings, scripts, workflow files,
outputs, or the package blob. The browser polls ``/__state`` and
reloads when the token bumps. Declared outputs are additionally
readable at ``/view/<path>`` — text as an escaped, syntax-highlighted
page, images and PDFs as raw bytes — and renderable at
``/preview/<path>`` when the project declares a ``[preview]`` recipe
for the suffix (:mod:`specthis.preview`; artifacts are cached outside
the tree). The declared-output set is the whole ACL: nothing an entry
does not claim is ever served.

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
from urllib.parse import quote, unquote

from .export import is_text_file, output_lang, raw_view_type, render
from .parse import Project, SpecError, load_project_lenient
from .preview import CONTENT_TYPES, default_cache_dir, find_recipe, render_preview

POLL_SECONDS = 1.0


def _watched_paths(root: Path, project: Project | None) -> list[Path]:
    """Everything the rendered view depends on."""
    paths = sorted((root / "specs").glob("*.md")) + sorted((root / "specs").glob("*.toml"))
    paths += sorted((root / "journal").glob("*.md"))
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


_VIEWER_CSS = """
:root { --fg: #1a1a1a; --muted: #5a5a5a; --bg: #fdfdfc;
  --border: #d8d4cc; --accent: #6b3f1d; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
  Roboto, sans-serif; color: var(--fg); background: var(--bg); }
header { position: sticky; top: 0; display: flex; gap: 0.9rem;
  align-items: baseline; padding: 0.6rem 1.1rem; background: #f7f4ee;
  border-bottom: 1px solid var(--border); font-size: 0.9rem; }
header code { font-weight: 600; }
header .size { color: var(--muted); font-size: 0.8rem; }
header .nav { margin-left: auto; display: flex; gap: 0.9rem; }
header .nav a { color: var(--accent); text-decoration: none;
  white-space: nowrap; }
.truncated { padding: 0.5rem 1.1rem; background: #f7ecc9; color: #7d4e00;
  font-size: 0.85rem; }
.fail-note { padding: 0.5rem 1.1rem; background: #f7d9d5; color: #a40e26;
  font-size: 0.85rem; }
pre { margin: 0; padding: 1rem 1.1rem; overflow: auto; font-size: 0.85rem;
  line-height: 1.5; }
pre code.hljs { padding: 0; background: transparent; }
"""

_HLJS_CDN = "https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build"
#: languages the viewer wants that the common hljs bundle does not ship
_HLJS_EXTRA = {"latex", "r", "julia"}

_VIEW_TRUNCATE_BYTES = 2_000_000  # a tab-freezing CSV is not a viewer's job
_HIGHLIGHT_MAX_BYTES = 500_000  # highlight.js chokes long before truncation


def _viewer_nav(rel: str, has_preview: bool, at_preview: bool = False) -> str:
    """The header's right-side links: preview/source toggle + dashboard."""
    links = ""
    if at_preview:
        links += f'<a href="/view/{html.escape(quote(rel))}">source</a>'
    elif has_preview:
        links += f'<a href="/preview/{html.escape(quote(rel))}">preview</a>'
    return f'<span class="nav">{links}<a href="/">&larr; dashboard</a></span>'


def render_output_page(rel: str, path: Path, has_preview: bool = False) -> str:
    """The ``/view/<output>`` page: escaped bytes plus CDN highlighting.

    Same trust and degradation story as the dashboard: content is
    escaped, never interpreted, and offline the CDN assets simply
    don't load, leaving readable plain text."""
    data = path.read_bytes()
    shown = data[:_VIEW_TRUNCATE_BYTES].decode("utf-8", errors="replace")
    note = (
        f'<div class="truncated">first {_VIEW_TRUNCATE_BYTES:,} bytes of '
        f"{len(data):,} — open the file itself for the rest</div>"
        if len(data) > _VIEW_TRUNCATE_BYTES
        else ""
    )
    lang = output_lang(rel)
    css_link, scripts = "", ""
    if len(data) <= _HIGHLIGHT_MAX_BYTES:
        css_link = f'<link rel="stylesheet" href="{_HLJS_CDN}/styles/github.min.css">'
        extra = (
            f'<script src="{_HLJS_CDN}/languages/{lang}.min.js"></script>'
            if lang in _HLJS_EXTRA
            else ""
        )
        scripts = (
            f'<script src="{_HLJS_CDN}/highlight.min.js"></script>{extra}'
            "<script>window.hljs && hljs.highlightAll();</script>"
        )
    name = html.escape(rel)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{name}</title>\n{css_link}<style>{_VIEWER_CSS}</style></head>\n"
        f"<body><header><code>{name}</code>"
        f'<span class="size">{len(data):,} bytes</span>'
        f"{_viewer_nav(rel, has_preview)}</header>\n"
        f'{note}<pre><code class="language-{html.escape(lang)}">'
        f"{html.escape(shown)}</code></pre>\n{scripts}</body></html>\n"
    )


def render_preview_failed_page(rel: str, command: str, log: str) -> str:
    """The ``/preview/<output>`` page when the recipe fails: the log.

    A failed compile is content, not a server error — the fragment (or
    its preamble) is what needs fixing. Failures are never cached, so a
    plain reload retries."""
    name = html.escape(rel)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>preview failed — {name}</title>\n<style>{_VIEWER_CSS}</style></head>\n"
        f"<body><header><code>{name}</code>"
        f"{_viewer_nav(rel, has_preview=False, at_preview=True)}</header>\n"
        '<div class="fail-note">preview recipe failed — fix and reload '
        "(failures are not cached)</div>\n"
        f"<pre><code>$ {html.escape(command)}\n\n{html.escape(log)}</code></pre>\n"
        "</body></html>\n"
    )


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
        self.preview_cache = default_cache_dir()
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

    def output_path(self, rel: str) -> Path | None:
        """Resolve a declared output to its on-disk path; None if undeclared.

        Membership in the declared-output set is the whole ACL — a
        request for anything an entry does not claim never reaches the
        filesystem, so traversal has nothing to traverse."""
        project = self._project
        if project is None:
            return None
        if rel not in {o for e in project.entries.values() for o in e.outputs}:
            return None
        path = (self.root / rel).resolve()
        return path if path.is_relative_to(self.root.resolve()) else None

    @property
    def project(self) -> Project | None:
        return self._project


def _make_handler(dashboard: Dashboard) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            token, page = dashboard.snapshot()
            if self.path in ("/", "/specs.html", "/index.html"):
                self._send(page.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/__state":
                self._send(json.dumps({"token": token}).encode("utf-8"), "application/json")
            elif self.path.startswith("/view/"):
                rel = unquote(self.path[len("/view/"):].split("?", 1)[0])
                target = dashboard.output_path(rel)
                raw_type = raw_view_type(rel)
                if target is None:
                    self.send_error(404, "Not a declared output")
                elif not target.is_file():
                    self.send_error(404, "Output bytes are not on this disk")
                elif raw_type is not None:
                    self._send(target.read_bytes(), raw_type)
                elif not is_text_file(target):
                    self.send_error(404, "Output is not viewable (binary)")
                else:
                    project = dashboard.project
                    has_preview = project is not None and find_recipe(project, rel) is not None
                    page = render_output_page(rel, target, has_preview=has_preview)
                    self._send(page.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path.startswith("/preview/"):
                rel = unquote(self.path[len("/preview/"):].split("?", 1)[0])
                target = dashboard.output_path(rel)
                project = dashboard.project
                recipe = find_recipe(project, rel) if project is not None else None
                if target is None:
                    self.send_error(404, "Not a declared output")
                elif recipe is None:
                    self.send_error(
                        404,
                        "No [preview] recipe for this suffix in specs/bindings.toml",
                    )
                elif not target.is_file():
                    self.send_error(404, "Output bytes are not on this disk")
                else:
                    assert project is not None
                    result = render_preview(project, rel, recipe, dashboard.preview_cache)
                    if result is None:  # bytes vanished between the checks
                        self.send_error(404, "Output bytes are not on this disk")
                    elif result.path is not None:
                        self._send(result.path.read_bytes(), CONTENT_TYPES[recipe.format])
                    else:
                        page = render_preview_failed_page(rel, recipe.command, result.log)
                        self._send(page.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
