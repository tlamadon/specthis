"""Dashboard renderer: specs/specs.html + _index.json + _routing.json.

All three artefacts are *regenerated views*, never sources of truth:
they join the parsed specs (:mod:`specthis.parse`), the derived
statuses (:mod:`specthis.check`), and the host-doc routing scan
(:mod:`specthis.routing`) — and nothing else. ``specthis check``
never reads them; deleting them changes no answer the ledger gives.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .check import Report, Status, check_project, frontier
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
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; background: #f6f7f9; color: #1f2328; }
main { max-width: 1080px; margin: 0 auto; padding: 24px 20px 80px; }
header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
header h1 { font-size: 22px; margin: 0; }
header .sub { color: #656d76; font-size: 13px; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0 22px; }
.chip { font-size: 13px; padding: 3px 10px; border-radius: 999px; background: #fff;
        border: 1px solid #d0d7de; color: #57606a; }
.chip b { color: #1f2328; }
.badge { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 9px;
         border-radius: 999px; white-space: nowrap; }
.badge.ready         { background: #dafbe1; color: #116329; }
.badge.stale         { background: #fff8c5; color: #7d4e00; }
.badge.audit         { background: #ffe8d9; color: #a04100; }
.badge.rejected      { background: #ffebe9; color: #a40e26; }
.badge.unimplemented { background: #eaeef2; color: #57606a; }
.badge.upstream      { background: #ddf4ff; color: #0969da; }
section.frontier { background: #fff; border: 1px solid #d0d7de; border-left: 4px solid #a04100;
                   border-radius: 8px; padding: 14px 18px; margin-bottom: 24px; }
section.frontier h2 { font-size: 15px; margin: 0 0 8px; }
section.frontier .waiting { color: #57606a; font-size: 13px; margin-top: 8px; }
.card { background: #fff; border: 1px solid #d0d7de; border-radius: 8px;
        padding: 16px 18px; margin-bottom: 18px; }
.card h2 { font-size: 17px; margin: 0; }
.card .head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.kind { font-size: 12px; color: #57606a; border: 1px solid #d0d7de; border-radius: 4px;
        padding: 1px 6px; }
.pair a, .dep a { color: #0969da; text-decoration: none; font-size: 13px; }
.dep { margin-top: 6px; font-size: 13px; color: #57606a; }
.dep .lbl { margin-right: 4px; }
table { border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 14px; }
th { text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
     color: #656d76; font-weight: 600; padding: 4px 10px 4px 0; border-bottom: 1px solid #d8dee4; }
td { padding: 7px 10px 7px 0; border-bottom: 1px solid #eef1f4; vertical-align: top; }
td code, .dep code { font-size: 12.5px; background: #f6f8fa; padding: 1px 5px; border-radius: 4px; }
.who { color: #57606a; font-size: 13px; }
.moved { color: #7d4e00; font-size: 13px; }
.empty { color: #8b949e; }
.r-ok  { color: #116329; }
.r-bad { color: #a40e26; font-weight: 600; }
.r-note { color: #8b949e; }
"""

_RELOAD_JS = """
if (location.protocol.startsWith('http')) {
  let token = null;
  setInterval(async () => {
    try {
      const r = await fetch('/__state', {cache: 'no-store'});
      const s = await r.json();
      if (token !== null && s.token !== token) location.reload();
      token = s.token;
    } catch (e) { /* server gone; keep trying */ }
  }, 1000);
}
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


def _entry_rows(spec: SpecFile, reports: dict[str, Report]) -> str:
    rows = []
    for entry in spec.entries:
        r = reports[entry.name]
        if r.vouch:
            note = f" — {r.vouch.note}" if r.vouch.note else ""
            vouch = f'{_e(r.vouch.verdict)} <span class="who">by {_e(r.vouch.attester)}, {_e(r.vouch.vouched[:10])}{_e(note)}</span>'
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


def _spec_card(
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
            pair = f'<span class="pair"><a href="#spec-{_e(other)}">&#8596; {_e(other)}</a></span>'
    tier = f" &middot; {_e(spec.tier)}" if spec.kind == "compute" else ""
    deps = []
    if spec.consumes:
        chips = " ".join(
            f'<a href="#{_e(_entry_anchor(c))}"><code>{_e(c)}</code></a>' for c in spec.consumes
        )
        deps.append(f'<div class="dep"><span class="lbl">consumes</span> {chips}</div>')
    if spec.references:
        chips = " ".join(
            f'<a href="#spec-{_e(Path(ref).stem)}"><code>{_e(ref)}</code></a>'
            for ref in spec.references
        )
        deps.append(f'<div class="dep"><span class="lbl">references</span> {chips}</div>')
    if spec.host_doc:
        deps.append(_routing_line(spec, routing.get(spec.name)))
    return (
        f'<div class="card" id="spec-{_e(spec.name)}"><div class="head">'
        f"<h2>{_e(spec.name)}</h2>"
        f'<span class="kind">{_e(spec.kind)}{tier}</span>{pair}</div>'
        + "".join(deps)
        + _entry_rows(spec, reports)
        + "</div>"
    )


def render_html(
    project: Project,
    reports: dict[str, Report],
    routing: dict[str, RoutingReport],
    generated: str,
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
            '<section class="frontier"><h2>Frontier — broken for local reasons</h2>'
            f"<table>{rows}</table>{waiting_html}</section>"
        )

    cards = "".join(
        _spec_card(spec, project, reports, routing)
        for spec in sorted(project.specs, key=lambda s: (_KIND_ORDER.get(s.kind, 9), s.name))
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>specthis &mdash; {_e(project.root.name)}</title>
<style>{_CSS}</style></head>
<body><main>
<header><h1>specthis &middot; {_e(project.root.name)}</h1>
<span class="sub">generated {_e(generated)} &middot; a regenerated view; the ledger never reads it</span></header>
<div class="chips">{chips}</div>
{frontier_html}
{cards}
</main><script>{_RELOAD_JS}</script></body></html>
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
