"""Dashboard renderer: specs/specs.html + _index.json + _routing.json.

The page is an mkdocs-style spec browser: a sticky sidebar lists every
spec file grouped by kind, hash routing shows one spec at a time (the
full markdown contract, rendered), and a "Status dashboard" section
carries the frontier and the cross-project entry table. Everything is
a *regenerated view*, never a source of truth: it joins the parsed
specs (:mod:`specthis.parse`), the derived statuses
(:mod:`specthis.check`), and the host-doc routing scan
(:mod:`specthis.routing`) — and nothing else. ``specthis check``
never reads these artefacts; deleting them changes no answer.

Spec files are the user's own repo content, so their markdown renders
as-is (raw HTML in a spec ends up in the page — the same trust level
as opening the file in an editor). Math renders via MathJax from a
CDN when the network allows; offline it degrades to raw ``$...$``.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import markdown as _markdown

from .check import LOCAL_BREAKS, Report, Status, check_project, frontier
from .parse import Project, SpecFile, load_project
from .routing import RoutingReport, build_routing_json, check_routing

_KIND_ORDER = {"meta": 0, "definitions": 1, "templates": 2, "compute": 3, "report": 4, "figure": 5}

_STATUS_CLASS = {
    Status.READY: "ready",
    Status.STALE: "stale",
    Status.AUDIT_NEEDED: "audit",
    Status.REJECTED: "rejected",
    Status.UNIMPLEMENTED: "unimplemented",
    Status.UPSTREAM_UNVERIFIED: "upstream",
}


def build_index(project: Project, reports: dict[str, Report]) -> dict:
    """The queryable JSON view: per spec, frontmatter + per-entry facts."""
    specs = []
    for spec in project.specs:
        entries = []
        for entry in spec.entries:
            r = reports[entry.name]
            entries.append(
                {
                    "name": entry.name,
                    "status": r.status.value,
                    "outputs": entry.outputs,
                    "scripts": entry.binding.scripts,
                    "workflows": entry.binding.workflows,
                    "executor": entry.binding.executor,
                    "spec_sha": r.spec_sha,
                    "code_sha": r.code_sha,
                    "vouch": asdict(r.vouch) if r.vouch else None,
                    "run": asdict(r.run) if r.run else None,
                    "moved": r.moved,
                }
            )
        specs.append(
            {
                "name": spec.name,
                "file": spec.path.name,
                "title": spec.title,
                "kind": spec.kind,
                "tier": spec.tier,
                "consumes": spec.consumes,
                "references": spec.references,
                "host_doc": spec.host_doc,
                "section_label": spec.section_label,
                "entries": entries,
            }
        )
    return {"specs": specs}


_CSS = """
:root {
  --fg: #1a1a1a; --muted: #5a5a5a; --bg: #fdfdfc;
  --code-bg: #f3f1ed; --border: #d8d4cc; --accent: #6b3f1d;
  --sidebar-bg: #f7f4ee;
  --kind-meta: #6e6e6e; --kind-definitions: #2e7d5b;
  --kind-templates: #6a3d8a; --kind-compute: #2e6e9e;
  --kind-report: #b85a1e; --kind-figure: #1f7a7a;
}
* { box-sizing: border-box; }
html { font-size: 16px; scroll-behavior: smooth; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       color: var(--fg); background: var(--bg); line-height: 1.55; }
.layout { display: grid; grid-template-columns: 300px 1fr; min-height: 100vh; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; } }

.sidebar { background: var(--sidebar-bg); border-right: 1px solid var(--border);
  position: sticky; top: 0; height: 100vh; overflow-y: auto;
  padding: 1.25rem 1rem; font-size: 0.9rem; }
.sidebar h1 { font-size: 1rem; margin: 0 0 0.75rem; padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--border); letter-spacing: 0.02em; }
.sidebar .meta-line { font-size: 0.75rem; color: var(--muted); margin: -0.4rem 0 1rem; }
.nav-group { margin-top: 1.1rem; }
.nav-group:first-child { margin-top: 0; }
.nav-group-header { margin: 0 0 0.35rem; padding-bottom: 0.15rem;
  border-bottom: 1px solid var(--border); }
.kind { font-size: 0.7rem; letter-spacing: 0.06em; text-transform: uppercase;
  font-weight: 700; }
.kind-meta { color: var(--kind-meta); }       .kind-definitions { color: var(--kind-definitions); }
.kind-templates { color: var(--kind-templates); } .kind-compute { color: var(--kind-compute); }
.kind-report { color: var(--kind-report); }   .kind-figure { color: var(--kind-figure); }
.nav-file { margin-bottom: 0.55rem; padding: 0.1rem 0 0.1rem 0.5rem;
  border-left: 3px solid transparent; }
html.js-routed .nav-file.active { border-left-color: var(--accent);
  background: rgba(107, 63, 29, 0.06); }
.nav-file a { font-weight: 600; color: var(--fg); text-decoration: none; }
.nav-file a:hover { color: var(--accent); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 0.35rem; vertical-align: baseline; }
.dot-break { background: #c5573a; } .dot-wait { background: #4a7fb5; }
.dot-ready { background: #4d9367; }

.content { max-width: 52rem; padding: 1.5rem 2rem 4rem; }
html.js-routed section.spec { display: none; }
html.js-routed section.spec.active { display: block; }
section.spec > h2.spec-title { font-size: 1.45rem; margin: 0.2rem 0 0.3rem; }
.spec-meta { display: flex; align-items: baseline; gap: 0.7rem; flex-wrap: wrap;
  color: var(--muted); font-size: 0.85rem; margin-bottom: 0.6rem; }
.spec-meta code, .dep code, td code, .md code { font-size: 0.8rem;
  background: var(--code-bg); padding: 1px 5px; border-radius: 4px; }
.pair a, .dep a { color: var(--accent); text-decoration: none; }
.dep { font-size: 0.85rem; color: var(--muted); margin-top: 4px; }
.dep .lbl { margin-right: 4px; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 18px; }
.chip { font-size: 0.8rem; padding: 3px 10px; border-radius: 999px; background: #fff;
  border: 1px solid var(--border); color: var(--muted); }
.chip b { color: var(--fg); }
.badge { display: inline-block; font-size: 0.72rem; font-weight: 600; padding: 2px 9px;
  border-radius: 999px; white-space: nowrap; }
.badge.ready         { background: #dff0e4; color: #1a5c33; }
.badge.stale         { background: #f7ecc9; color: #7d4e00; }
.badge.audit         { background: #f9e0cd; color: #a04100; }
.badge.rejected      { background: #f7d9d5; color: #a40e26; }
.badge.unimplemented { background: #ebe8e2; color: #5a5a5a; }
.badge.upstream      { background: #dce9f5; color: #23629c; }
.frontier { background: #fff; border: 1px solid var(--border);
  border-left: 4px solid #a04100; border-radius: 8px; padding: 12px 16px;
  margin-bottom: 20px; }
.frontier h3 { font-size: 0.95rem; margin: 0 0 6px; }
.frontier .waiting { color: var(--muted); font-size: 0.85rem; margin-top: 6px; }
.warnings { background: #fff; border: 1px solid var(--border);
  border-left: 4px solid #b85a1e; border-radius: 8px; padding: 12px 16px;
  margin-bottom: 20px; font-size: 0.9rem; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 0.9rem; }
th { text-align: left; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: .04em; color: var(--muted); font-weight: 600;
  padding: 4px 10px 4px 0; border-bottom: 1px solid var(--border); }
td { padding: 6px 10px 6px 0; border-bottom: 1px solid #eae6de; vertical-align: top; }
td a { color: var(--accent); text-decoration: none; }
.who { color: var(--muted); font-size: 0.82rem; }
.moved { color: #7d4e00; font-size: 0.82rem; }
.empty { color: #9a958c; }
.r-ok  { color: #1a5c33; }
.r-bad { color: #a40e26; font-weight: 600; }
.r-note { color: #9a958c; }

.md { margin-top: 1.2rem; border-top: 1px solid var(--border); padding-top: 0.8rem; }
.md h1 { font-size: 1.3rem; margin: 1rem 0 0.4rem; }
.md h2 { font-size: 1.12rem; margin: 1rem 0 0.4rem; }
.md h3 { font-size: 0.98rem; margin: 0.8rem 0 0.3rem; }
.md p, .md ul, .md ol { margin: 6px 0; }
.md pre { background: var(--code-bg); border: 1px solid var(--border);
  border-radius: 6px; padding: 10px 12px; overflow-x: auto; }
.md pre code { background: none; padding: 0; }
.md table { width: auto; }
.md th, .md td { border: 1px solid var(--border); padding: 4px 10px; }
.md blockquote { border-left: 3px solid var(--border); margin: 6px 0;
  padding: 0 12px; color: var(--muted); }

.back-to-status { position: fixed; bottom: 1rem; right: 1rem;
  background: var(--accent); color: #fff; padding: 0.5rem 0.85rem;
  border-radius: 999px; font-size: 0.75rem; font-weight: 600;
  letter-spacing: 0.04em; text-decoration: none;
  box-shadow: 0 2px 6px rgba(0,0,0,0.18); opacity: 0.85; }
.back-to-status:hover { opacity: 1; color: #fff; }
@media (max-width: 900px) { .back-to-status { display: none; } }
"""

_ROUTER_JS = """
(function () {
  const sections = Array.from(document.querySelectorAll('section.spec'));
  const navFiles = Array.from(document.querySelectorAll('.nav-file'));
  if (sections.length === 0) return;

  const anchorToFile = {};
  for (const s of sections) {
    anchorToFile[s.id] = s.id;
    s.querySelectorAll('[id]').forEach((el) => { anchorToFile[el.id] = s.id; });
  }

  function route() {
    const hash = (location.hash || '').replace(/^#/, '');
    const target = (hash && anchorToFile[hash]) || sections[0].id;
    for (const s of sections) { s.classList.toggle('active', s.id === target); }
    for (const nv of navFiles) {
      nv.classList.toggle('active', nv.dataset.fileAnchor === target);
    }
    if (hash && hash !== target) {
      const el = document.getElementById(hash);
      if (el) el.scrollIntoView({block: 'start'});
    } else {
      window.scrollTo(0, 0);
    }
  }

  window.addEventListener('hashchange', route);
  route();

  // Live reload (when served): poll the state token, preserve scroll.
  if (location.protocol.startsWith('http')) {
    let token = null;
    setInterval(async () => {
      try {
        const r = await fetch('/__state', {cache: 'no-store'});
        const s = await r.json();
        if (token !== null && s.token !== token) {
          sessionStorage.setItem('specsScrollY', String(window.scrollY));
          location.reload();
        }
        token = s.token;
      } catch (e) { /* server gone; keep trying */ }
    }, 1000);
    window.addEventListener('load', () => {
      const y = sessionStorage.getItem('specsScrollY');
      if (y !== null) {
        sessionStorage.removeItem('specsScrollY');
        window.scrollTo(0, parseInt(y, 10));
      }
    });
  }
})();
"""

_MATHJAX = """
<script>
window.MathJax = { tex: { inlineMath: [['$','$'], ['\\\\(','\\\\)']],
                          displayMath: [['$$','$$'], ['\\\\[','\\\\]']] } };
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
"""


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _badge(status: Status) -> str:
    return f'<span class="badge {_STATUS_CLASS[status]}">{_e(status.value)}</span>'


def _hint(report: Report, project: Project) -> str:
    if report.status is Status.UNIMPLEMENTED:
        return "no code at " + ", ".join(project.entries[report.entry].binding.scripts)
    if report.status is Status.AUDIT_NEEDED:
        return "spec or code moved since vouch" if report.vouch else "never vouched"
    if report.status is Status.REJECTED and report.vouch is not None:
        v = report.vouch
        return f"rejected by {v.attester}" + (f": {v.note}" if v.note else "")
    if report.status is Status.STALE:
        return "never run" if report.run is None else "moved: " + ", ".join(report.moved)
    return ""


def _entry_anchor(name: str) -> str:
    return f"entry-{name}"


def _spec_anchor(name: str) -> str:
    return f"spec-{name}"


def _entry_rows(spec: SpecFile, reports: dict[str, Report]) -> str:
    rows = []
    for entry in spec.entries:
        r = reports[entry.name]
        if r.vouch:
            note = f" — {r.vouch.note}" if r.vouch.note else ""
            vouch = (
                f'{_e(r.vouch.verdict)} <span class="who">by {_e(r.vouch.attester)}, '
                f"{_e(r.vouch.vouched[:10])}{_e(note)}</span>"
            )
        else:
            vouch = '<span class="empty">—</span>'
        if r.run:
            run = f'<span class="who">{_e(r.run.ran[:10])} via {_e(r.run.executor)}</span>'
        else:
            run = '<span class="empty">—</span>'
        outputs = "<br>".join(f"<code>{_e(o)}</code>" for o in entry.outputs)
        moved = (
            f'<div class="moved">moved: {_e(", ".join(r.moved))}</div>'
            if r.moved and r.status is Status.STALE
            else ""
        )
        rows.append(
            f'<tr id="{_e(_entry_anchor(entry.name))}">'
            f"<td><b>{_e(entry.name)}</b></td>"
            f"<td>{_badge(r.status)}{moved}</td>"
            f"<td>{outputs}</td>"
            f"<td>{vouch}</td>"
            f"<td>{run}</td></tr>"
        )
    if not rows:
        return ""
    return (
        "<table><tr><th>entry</th><th>status</th><th>outputs</th>"
        "<th>vouched</th><th>last run</th></tr>" + "".join(rows) + "</table>"
    )


def _routing_line(spec: SpecFile, rr: RoutingReport | None) -> str:
    head = f'<span class="lbl">routes to</span> <code>{_e(spec.host_doc)}</code>' + (
        f" &sect; <code>{_e(spec.section_label)}</code>" if spec.section_label else ""
    )
    if rr is None:
        return f'<div class="dep">{head}</div>'
    if not rr.host_doc_exists:
        return f'<div class="dep">{head} <span class="r-bad">&#10007; host doc missing</span></div>'
    if not rr.label_found:
        return f'<div class="dep">{head} <span class="r-bad">&#10007; label not found</span></div>'
    marks = " ".join(
        f'<span class="r-ok">&#10003; <code>{_e(Path(out).name)}</code></span>'
        if ok
        else f'<span class="r-bad">&#10007; <code>{_e(Path(out).name)}</code> orphaned</span>'
        for out, ok in rr.routed.items()
    )
    extra = (
        f' <span class="r-note">section also inputs: {_e(", ".join(rr.extra_inputs))}</span>'
        if rr.extra_inputs
        else ""
    )
    return f'<div class="dep">{head} {marks}{extra}</div>'


def _worst_dot(spec: SpecFile, reports: dict[str, Report]) -> str:
    statuses = {reports[e.name].status for e in spec.entries}
    if not statuses:
        return ""
    if statuses & LOCAL_BREAKS:
        return '<span class="dot dot-break"></span>'
    if Status.UPSTREAM_UNVERIFIED in statuses:
        return '<span class="dot dot-wait"></span>'
    return '<span class="dot dot-ready"></span>'


def _sidebar(project: Project, reports: dict[str, Report], generated: str) -> str:
    groups: dict[str, list[SpecFile]] = {}
    for spec in sorted(project.specs, key=lambda s: s.name):
        groups.setdefault(spec.kind, []).append(spec)

    parts = [
        '<nav class="sidebar">',
        f"<h1>{_e(project.root.name)} &middot; specs/</h1>",
        f'<div class="meta-line">{len(project.specs)} files &middot; generated {_e(generated[:10])}</div>',
        '<div class="nav-group">'
        '<div class="nav-file" data-file-anchor="status">'
        '<a href="#status">Status dashboard</a></div></div>',
    ]
    for kind in sorted(groups, key=lambda k: _KIND_ORDER.get(k, 9)):
        parts.append(
            f'<div class="nav-group"><div class="nav-group-header">'
            f'<span class="kind kind-{_e(kind)}">{_e(kind)}</span></div>'
        )
        for spec in groups[kind]:
            anchor = _spec_anchor(spec.name)
            parts.append(
                f'<div class="nav-file" data-file-anchor="{_e(anchor)}">'
                f"{_worst_dot(spec, reports)}"
                f'<a href="#{_e(anchor)}" title="{_e(spec.path.name)}">{_e(spec.title)}</a></div>'
            )
        parts.append("</div>")
    parts.append("</nav>")
    return "".join(parts)


def _status_section(
    project: Project,
    reports: dict[str, Report],
    routing: dict[str, RoutingReport],
) -> str:
    local, waiting, _ready = frontier(reports)
    counts: dict[Status, int] = {}
    for r in reports.values():
        counts[r.status] = counts.get(r.status, 0) + 1
    chips = "".join(
        f'<span class="chip"><b>{counts[s]}</b> {_e(s.value)}</span>'
        for s in Status
        if counts.get(s)
    ) or '<span class="chip">no entries yet</span>'

    frontier_html = ""
    if local:
        rows = "".join(
            f'<tr><td><a href="#{_e(_entry_anchor(r.entry))}"><b>{_e(r.entry)}</b></a></td>'
            f"<td>{_badge(r.status)}</td><td>{_e(_hint(r, project))}</td></tr>"
            for r in sorted(local, key=lambda r: r.entry)
        )
        waiting_html = (
            f'<div class="waiting">waiting on the frontier: {waiting} upstream-unverified</div>'
            if waiting
            else ""
        )
        frontier_html = (
            '<div class="frontier"><h3>Frontier — broken for local reasons</h3>'
            f"<table>{rows}</table>{waiting_html}</div>"
        )

    warn_items = []
    for rr in routing.values():
        if not rr.host_doc_exists:
            warn_items.append(f"{_e(rr.spec)}: host doc <code>{_e(rr.host_doc)}</code> missing")
        elif not rr.label_found:
            warn_items.append(
                f"{_e(rr.spec)}: label <code>{_e(rr.section_label)}</code> "
                f"not found in <code>{_e(rr.host_doc)}</code>"
            )
        else:
            for out in rr.orphaned:
                warn_items.append(
                    f"{_e(rr.spec)}: <code>{_e(out)}</code> exported but never "
                    f"input by <code>{_e(rr.host_doc)}</code>"
                )
    warnings_html = (
        '<div class="warnings"><b>Routing warnings</b><ul>'
        + "".join(f"<li>{w}</li>" for w in warn_items)
        + "</ul></div>"
        if warn_items
        else ""
    )

    all_rows = "".join(
        f'<tr><td><a href="#{_e(_entry_anchor(name))}"><b>{_e(name)}</b></a></td>'
        f'<td><a href="#{_e(_spec_anchor(e.spec.name))}">{_e(e.spec.name)}</a></td>'
        f"<td>{_badge(reports[name].status)}</td>"
        f"<td>{_e(e.spec.kind)}/{_e(e.tier)}</td></tr>"
        for name, e in sorted(project.entries.items())
    )
    all_table = (
        "<table><tr><th>entry</th><th>spec</th><th>status</th><th>kind/tier</th></tr>"
        + all_rows
        + "</table>"
        if all_rows
        else '<p class="empty">No entries yet.</p>'
    )

    return (
        '<section class="spec" id="status">'
        '<h2 class="spec-title">Status dashboard</h2>'
        f'<div class="chips">{chips}</div>'
        f"{frontier_html}{warnings_html}{all_table}</section>"
    )


def _spec_section(
    spec: SpecFile,
    project: Project,
    reports: dict[str, Report],
    routing: dict[str, RoutingReport],
) -> str:
    spec_names = {s.name for s in project.specs}
    pair = ""
    for a, b in (("compute-", "report-"), ("report-", "compute-")):
        if spec.name.startswith(a) and (b + spec.name[len(a):]) in spec_names:
            other = b + spec.name[len(a):]
            pair = (
                f'<span class="pair"><a href="#{_e(_spec_anchor(other))}">'
                f"&#8596; {_e(other)}</a></span>"
            )
    tier = f"&middot; {_e(spec.tier)}" if spec.kind == "compute" else ""
    meta = (
        f'<div class="spec-meta"><span class="kind kind-{_e(spec.kind)}">{_e(spec.kind)}</span> '
        f"{tier} <code>{_e(spec.path.name)}</code> {pair}</div>"
    )
    deps = []
    if spec.consumes:
        chips = " ".join(
            f'<a href="#{_e(_entry_anchor(c))}"><code>{_e(c)}</code></a>' for c in spec.consumes
        )
        deps.append(f'<div class="dep"><span class="lbl">consumes</span> {chips}</div>')
    if spec.references:
        chips = " ".join(
            f'<a href="#{_e(_spec_anchor(Path(ref).stem))}"><code>{_e(ref)}</code></a>'
            for ref in spec.references
        )
        deps.append(f'<div class="dep"><span class="lbl">references</span> {chips}</div>')
    if spec.host_doc:
        deps.append(_routing_line(spec, routing.get(spec.name)))

    body_html = ""
    if spec.body.strip():
        rendered = _markdown.markdown(spec.body, extensions=["tables", "fenced_code"])
        body_html = f'<div class="md">{rendered}</div>'

    return (
        f'<section class="spec" id="{_e(_spec_anchor(spec.name))}">'
        f'<h2 class="spec-title">{_e(spec.title)}</h2>{meta}'
        + "".join(deps)
        + _entry_rows(spec, reports)
        + body_html
        + "</section>"
    )


def render_html(
    project: Project,
    reports: dict[str, Report],
    routing: dict[str, RoutingReport],
    generated: str,
) -> str:
    sections = [_status_section(project, reports, routing)] + [
        _spec_section(spec, project, reports, routing)
        for spec in sorted(project.specs, key=lambda s: (_KIND_ORDER.get(s.kind, 9), s.name))
    ]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>specs/ &mdash; {_e(project.root.name)}</title>
<script>document.documentElement.classList.add('js-routed');</script>
<style>{_CSS}</style>
{_MATHJAX}</head>
<body><div class="layout">
{_sidebar(project, reports, generated)}
<main class="content">
{"".join(sections)}
</main></div>
<a class="back-to-status" href="#status">status</a>
<script>{_ROUTER_JS}</script></body></html>
"""


def render(project: Project) -> tuple[str, dict, dict]:
    """One joined view: (specs.html text, _index.json data, _routing.json data)."""
    reports = check_project(project)
    routing = {r.spec: r for r in check_routing(project)}
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        render_html(project, reports, routing, generated),
        build_index(project, reports),
        build_routing_json(project),
    )


def write_artefacts(root: Path) -> list[Path]:
    """Render and write specs/specs.html + _index.json + _routing.json."""
    project = load_project(root)
    html_text, index, routing = render(project)
    targets = {
        project.specs_dir / "specs.html": html_text,
        project.specs_dir / "_index.json": json.dumps(index, indent=2) + "\n",
        project.specs_dir / "_routing.json": json.dumps(routing, indent=2) + "\n",
    }
    for path, content in targets.items():
        path.write_text(content, encoding="utf-8")
    return list(targets)
