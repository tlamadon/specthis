"""Dashboard renderer: specs/specs.html + _index.json.

The page is an mkdocs-style spec browser: a sticky sidebar lists every
spec file grouped by frontmatter ``group:`` (ranked by ``priority:``,
higher first; untagged specs fall back to kind groups below, each row
carrying a small kind/tier pill), and hash routing shows one page at a
time. The two trees get one page each: the **Vouch tree** (the
landing) carries every definition's trust state — attester, vouch
date, judgment cost, what moved since — above the spec-level DAG
(:mod:`specthis.dag` — a git-log-style rails list in story order;
on this page rails AND entry dots speak the vouch axis), with rows
expandable into detail cards and focusable on one entry's
upstream/downstream slice; the **Run tree** carries every
realization's state — ran when, via what, duration, byte locality,
what moved — for entries with a run axis (libraries stop at code).
An **Activity log** lists each entry's current ledger claims plus the
journal, newest first. Everything is
a *regenerated view*, never a source of truth: it joins the parsed
specs (:mod:`specthis.parse`), the derived statuses
(:mod:`specthis.check`), and the journal narratives
(:mod:`specthis.journal`) — and nothing else. ``specthis check``
never reads these artefacts; deleting them changes no answer.

Spec files are the user's own repo content, so their markdown renders
as-is (raw HTML in a spec ends up in the page — the same trust level
as opening the file in an editor). Math renders via MathJax from a
CDN when the network allows; offline it degrades to raw ``$...$``.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import markdown as _markdown

from .check import (
    Certification,
    Realization,
    Report,
    check_project,
    machine_repairable,
)
from .dag import dag_svg
from .icons import ICONS
from .journal import JournalEntry, load_journal
from .parse import _FRONTMATTER, Entry, Problem, Project, SpecFile, load_project_lenient
from .timefmt import fmt_ago, fmt_duration

_KIND_ORDER = {
    "meta": 0,
    "definitions": 1,
    "library": 2,
    "templates": 3,
    "compute": 4,
    "report": 5,
}



def _consumed_by(project: Project) -> dict[str, list[str]]:
    """Reverse of ``consumes`` over the active entries (downstream edges)."""
    rev: dict[str, list[str]] = {}
    for name, e in sorted(project.entries.items()):
        for up in e.consumes:
            rev.setdefault(up, []).append(name)
    return rev


def build_index(
    project: Project,
    reports: dict[str, Report],
    journal: list[JournalEntry] | None = None,
) -> dict:
    """The queryable JSON view: per spec, frontmatter + per-entry facts."""
    consumed_by = _consumed_by(project)
    specs = []
    for spec in project.specs:
        entries = []
        for entry in spec.entries:
            r = reports.get(entry.name)
            if r is None:  # dormant under skip: true
                entries.append(
                    {"name": entry.name, "status": "skipped", "outputs": entry.outputs}
                )
                continue
            entries.append(
                {
                    "name": entry.name,
                    "status": r.status.value,
                    "certification": r.certification.value,
                    "realization": r.realization.value if r.realization else None,
                    "computable": r.computable,
                    "realized": r.realized,
                    "outputs": entry.outputs,
                    "scripts": entry.binding.scripts,
                    "workflows": entry.binding.workflows,
                    "executor": entry.binding.executor,
                    "spec_sha": r.spec_sha,
                    "code_sha": r.code_sha,
                    "vouch": asdict(r.vouch) if r.vouch else None,
                    "run": asdict(r.run) if r.run else None,
                    "moved": r.moved,
                    "materialized": r.materialized,
                    "consumes": entry.consumes,
                    "consumed_by": consumed_by.get(entry.name, []),
                }
            )
        specs.append(
            {
                "name": spec.name,
                "file": spec.path.name,
                "title": spec.title,
                "kind": spec.kind,
                "skip": spec.skip,
                "tier": spec.tier,
                "group": spec.group,
                "priority": spec.priority,
                "consumes": spec.consumes,
                "references": spec.references,
                "entries": entries,
            }
        )
    return {
        "specs": specs,
        "journal": [
            {"file": f"journal/{j.path.name}", "date": j.date, "title": j.title}
            for j in (journal or [])
        ],
    }


_CSS = """
:root {
  --fg: #1a1a1a; --muted: #5a5a5a; --bg: #fdfdfc;
  --code-bg: #f3f1ed; --border: #d8d4cc; --accent: #6b3f1d;
  --sidebar-bg: #f7f4ee;
  --kind-meta: #6e6e6e; --kind-definitions: #2e7d5b;
  --kind-templates: #6a3d8a; --kind-compute: #2e6e9e;
  --kind-report: #b85a1e;
  --kind-library: #8a6d1f; --kind-journal: #335c81;
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
.kind-report { color: var(--kind-report); }
.kind-library { color: var(--kind-library); }
.kind-journal { color: var(--kind-journal); }
.kind-broken { color: #a40e26; }
.kind-custom { color: var(--accent); }
.pill { display: inline-flex; align-items: center; justify-content: center;
  width: 15px; height: 15px; border-radius: 50%;
  border: 1px solid currentColor; opacity: 0.65; flex: none; }
.pill svg { width: 9px; height: 9px; display: block; }
.pill-tier { color: var(--muted); }
.nav-file { margin-bottom: 0.55rem; padding: 0.1rem 0 0.1rem 0.5rem;
  border-left: 3px solid transparent; display: flex; align-items: baseline; }
.nav-file a { min-width: 0; }
.nav-file .dot { flex: none; }
.nav-file .pills { margin-left: auto; padding-left: 0.4rem; display: flex;
  gap: 3px; flex: none; align-self: center; }
html.js-routed .nav-file.active { border-left-color: var(--accent);
  background: rgba(107, 63, 29, 0.06); }
.nav-file a { font-weight: 600; color: var(--fg); text-decoration: none; }
.nav-file a:hover { color: var(--accent); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 0.35rem; vertical-align: baseline; }
.dot-break { background: #c5573a; } .dot-wait { background: #4a7fb5; }
.dot-ready { background: #4d9367; } .dot-skip { background: #b9b3a7; }
.nav-file.skipped a { color: var(--muted); font-weight: 400; font-style: italic; }
section.spec.skipped .md, section.spec.skipped table { opacity: 0.65; }

.content { max-width: 52rem; padding: 1.5rem 2rem 4rem; }
html.js-routed section.spec { display: none; }
html.js-routed section.spec.active { display: block; }
section.spec > h2.spec-title { font-size: 1.45rem; margin: 0.2rem 0 0.3rem; }
.spec-meta { display: flex; align-items: baseline; gap: 0.7rem; flex-wrap: wrap;
  color: var(--muted); font-size: 0.85rem; margin-bottom: 0.6rem; }
.spec-meta code, .dep code, td code, .md code { font-size: 0.8rem;
  background: var(--code-bg); padding: 1px 5px; border-radius: 4px; }
.pair a, .dep a { color: var(--accent); text-decoration: none; }
.output-link[href] { text-decoration: none; }
.output-link[href] code { cursor: pointer;
  text-decoration: underline dotted var(--muted); text-underline-offset: 2px; }
.output-link[href]:hover code { color: var(--accent);
  text-decoration-color: var(--accent); }
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
.badge.skipped       { background: #eeece6; color: #8a857a; }
.badge.remote-bytes  { background: #e8e4f4; color: #4b3d8f; }
.badge.evt-vouch     { background: #dff0e4; color: #1a5c33; }
.badge.evt-run       { background: #dce9f5; color: #23629c; }
.badge.evt-journal   { background: #eeece6; color: #8a857a; }
.warnings { background: #fff; border: 1px solid var(--border);
  border-left: 4px solid #b85a1e; border-radius: 8px; padding: 12px 16px;
  margin-bottom: 20px; font-size: 0.9rem; }
.warnings.problems { border-left-color: #a40e26; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 0.9rem; }
th { text-align: left; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: .04em; color: var(--muted); font-weight: 600;
  padding: 4px 10px 4px 0; border-bottom: 1px solid var(--border); }
td { padding: 6px 10px 6px 0; border-bottom: 1px solid #eae6de; vertical-align: top; }
td a { color: var(--accent); text-decoration: none; }
table.sortable th { cursor: pointer; user-select: none; white-space: nowrap; }
table.sortable th:hover { color: var(--fg); }
table.sortable th.sort-asc::after { content: " \\25B4"; }
table.sortable th.sort-desc::after { content: " \\25BE"; }
table.sortable th.no-sort { cursor: default; }

.focus-bar[hidden] { display: none; } /* author display:flex beats the UA [hidden] rule */
.focus-bar { display: flex; align-items: center; gap: 10px; font-size: 0.85rem;
  background: #fff; border: 1px solid var(--border);
  border-left: 4px solid var(--accent); border-radius: 8px;
  padding: 8px 12px; margin-bottom: 12px; }
.focus-bar button { border: 1px solid var(--border); background: var(--bg);
  border-radius: 999px; font-size: 0.75rem; padding: 2px 10px; cursor: pointer;
  color: var(--muted); margin-left: auto; }
.focus-bar button:hover { color: var(--accent); border-color: var(--accent); }
.focus-cell { white-space: nowrap; }
.focus-btn { border: none; background: none; cursor: pointer; padding: 0;
  color: #b9b3a7; font-size: 0.95rem; line-height: 1; }
.focus-btn:hover { color: var(--accent); }
tr.entry-row.focused .focus-btn { color: var(--accent); }
.dir { font-size: 0.8rem; color: var(--muted); margin-left: 4px; }
tr.entry-row { cursor: pointer; }
tr.entry-row:hover td { background: rgba(107, 63, 29, 0.04); }
tr.detail { display: none; }
tr.detail.open { display: table-row; }
tr.detail > td { padding: 2px 0 10px; }
.detail-card { background: var(--sidebar-bg); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 12px; font-size: 0.85rem; }
.detail-card .dep { color: var(--fg); margin-top: 2px; }
.detail-card .lbl { display: inline-block; min-width: 92px; color: var(--muted); }
.who { color: var(--muted); font-size: 0.82rem; }
.moved { color: #7d4e00; font-size: 0.82rem; }
.empty { color: #9a958c; }

/* spec-level DAG strip: consumes flow, one node per spec, a dot per entry */
.dag-wrap { overflow-x: auto; margin: 2px 0 4px; }
.dag { display: block; }
.dag a { text-decoration: none; }
.dag .dag-node .box { fill: #fff; stroke: var(--border); stroke-width: 1.2; }
.dag .dag-node:hover .box { stroke: var(--accent); }
.dag .dag-node text { font-size: 12px; font-weight: 600; fill: var(--fg); }
.dag .dag-node text.cnt { font-size: 10px; fill: #5a5a5a; }
.dag .dag-node text.meta { font-size: 10px; font-weight: 400; fill: var(--muted); }
.dag .dag-node.skipped { opacity: 0.55; }
.dag .dag-node.skipped .box { stroke-dasharray: 4 3; }
.dag .edge { fill: none; stroke: #b9b3a7; stroke-width: 1.3; }
.dag .rail { fill: none; stroke-width: 2; stroke-linecap: round; opacity: 0.45;
  transition: opacity 0.12s; }
.dag.rails-hover .rail { opacity: 0.1; }
.dag.rails-hover .rail.hot { opacity: 0.9; }
.dag .hit { fill: none; pointer-events: all; }
.dag-caption { font-size: 0.78rem; color: var(--muted); margin: 0 0 16px; }

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

/* journal: dates, filter box, card grid (mirrors the POC dashboard) */
.journal-date { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85em; color: var(--muted); margin-right: 0.4rem; }
.nav-file .journal-date { font-size: 0.78em; margin-right: 0.3rem; }
.nav-file a + .journal-date { margin-left: 0.3rem; }
.journal-filter { display: flex; align-items: center; gap: 0.6rem;
  margin: 0.4rem 0 1rem; }
.journal-filter input { flex: 1 1 auto; padding: 0.5rem 0.7rem;
  font-size: 0.95rem; border: 1px solid var(--border); border-radius: 4px;
  background: var(--bg); color: inherit; min-width: 0; }
.journal-filter input:focus { outline: none; border-color: var(--kind-journal);
  box-shadow: 0 0 0 2px rgba(51, 92, 129, 0.18); }
.journal-filter-count { font-family: ui-monospace, monospace;
  font-size: 0.8em; color: var(--muted); white-space: nowrap; }
.journal-cards { display: grid; gap: 0.7rem;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  margin: 0 0 1.4rem; }
.journal-card { display: flex; flex-direction: column; gap: 0.3rem;
  padding: 0.7rem 0.85rem; border: 1px solid var(--border); border-radius: 5px;
  background: var(--bg); color: inherit; text-decoration: none;
  transition: border-color 0.12s, box-shadow 0.12s, transform 0.12s; }
.journal-card:hover { border-color: var(--kind-journal);
  box-shadow: 0 2px 6px rgba(51, 92, 129, 0.15); transform: translateY(-1px); }
.journal-card-date { font-family: ui-monospace, monospace; font-size: 0.78em;
  color: var(--muted); letter-spacing: 0.02em; }
.journal-card-title { font-size: 0.95em; font-weight: 600; line-height: 1.3;
  color: inherit; }
.journal-card.is-hidden { display: none; }

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
  // Output chips link to the dev server's /view/ pages; opened from
  // file:// there is no server, so degrade them back to plain chips.
  if (!location.protocol.startsWith('http')) {
    document.querySelectorAll('a.output-link').forEach((a) => {
      a.removeAttribute('href');
      a.title = 'outputs are viewable when served: specthis serve';
    });
  }

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

  // Sortable tables: click a header to sort by that column, click
  // again to reverse. Cells opt into a custom key via data-sort
  // (numbers compare numerically); empty keys always sort last. A
  // row's detail row (the expandable card) travels with it.
  document.querySelectorAll('table.sortable').forEach((table) => {
    const tbody = table.tBodies[0];
    const headers = Array.from(table.tHead ? table.tHead.rows[0].cells : []);
    headers.forEach((th, col) => {
      if (th.classList.contains('no-sort')) return;
      th.addEventListener('click', () => {
        const asc = !th.classList.contains('sort-asc');
        headers.forEach((h) => h.classList.remove('sort-asc', 'sort-desc'));
        th.classList.add(asc ? 'sort-asc' : 'sort-desc');
        const key = (tr) => {
          const td = tr.cells[col];
          if (!td) return '';
          const s = td.dataset.sort;
          return s !== undefined ? s : td.textContent.trim().toLowerCase();
        };
        Array.from(tbody.rows)
          .filter((tr) => !tr.classList.contains('detail'))
          .map((tr) => {
            const next = tr.nextElementSibling;
            const detail = next && next.classList.contains('detail') ? next : null;
            return [key(tr), tr, detail];
          })
          .sort((a, b) => {
            if (a[0] === '' || b[0] === '') {
              return (a[0] === '' ? 1 : 0) - (b[0] === '' ? 1 : 0);
            }
            const na = Number(a[0]);
            const nb = Number(b[0]);
            const cmp = !Number.isNaN(na) && !Number.isNaN(nb)
              ? na - nb : a[0].localeCompare(b[0]);
            return asc ? cmp : -cmp;
          })
          .forEach((row) => {
            tbody.appendChild(row[1]);
            if (row[2]) tbody.appendChild(row[2]);
          });
      });
    });
  });

  // Entry focus + detail cards. Vouch-tree rows carry the DAG
  // (data-consumes); focusing an entry there hides everything outside
  // its upstream/downstream closure. Clicking ANY entry row (either
  // tree page) toggles its detail card. Focus survives the
  // live-reload cycle via sessionStorage, like scroll does.
  const entryRows = Array.from(document.querySelectorAll('tr.entry-row'));
  const focusRows = Array.from(document.querySelectorAll('#vouch tr.entry-row'));
  if (entryRows.length) {
    const up = {};
    const down = {};
    focusRows.forEach((tr) => {
      const name = tr.dataset.name;
      up[name] = (tr.dataset.consumes || '').split(' ').filter(Boolean);
      up[name].forEach((c) => { (down[c] = down[c] || []).push(name); });
    });
    const closure = (start, edges) => {
      const seen = new Set();
      const queue = [start];
      while (queue.length) {
        for (const next of edges[queue.pop()] || []) {
          if (!seen.has(next)) { seen.add(next); queue.push(next); }
        }
      }
      return seen;
    };
    const detailOf = (tr) => {
      const next = tr.nextElementSibling;
      return next && next.classList.contains('detail') ? next : null;
    };
    const bar = document.getElementById('focus-bar');
    let current = null;
    const apply = (name) => {
      current = name;
      const ups = name ? closure(name, up) : null;
      const downs = name ? closure(name, down) : null;
      let shown = 0;
      focusRows.forEach((tr) => {
        const n = tr.dataset.name;
        const visible = !name || n === name || ups.has(n) || downs.has(n);
        tr.hidden = !visible;
        tr.classList.toggle('focused', n === name);
        const detail = detailOf(tr);
        if (detail && !visible) detail.classList.remove('open');
        const dir = tr.querySelector('.dir');
        if (dir) {
          dir.textContent = !name || n === name ? ''
            : (ups.has(n) ? '\\u2191' : (downs.has(n) ? '\\u2193' : ''));
        }
        if (visible) shown += 1;
      });
      if (bar) {
        bar.hidden = !name;
        if (name) {
          document.getElementById('focus-name').textContent = name;
          document.getElementById('focus-counts').textContent =
            '\\u2014 ' + ups.size + ' upstream, ' + downs.size +
            ' downstream (' + shown + ' of ' + focusRows.length + ' entries shown)';
        }
      }
      if (name) sessionStorage.setItem('specsFocus', name);
      else sessionStorage.removeItem('specsFocus');
    };
    entryRows.forEach((tr) => {
      const btn = tr.querySelector('.focus-btn');
      if (btn) {
        btn.addEventListener('click', () => {
          apply(current === tr.dataset.name ? null : tr.dataset.name);
        });
      }
      tr.addEventListener('click', (ev) => {
        if (ev.target.closest('a, button')) return;
        const detail = detailOf(tr);
        if (detail) detail.classList.toggle('open');
      });
    });
    const clear = document.getElementById('focus-clear');
    if (clear) clear.addEventListener('click', () => apply(null));
    const saved = sessionStorage.getItem('specsFocus');
    if (saved && focusRows.some((tr) => tr.dataset.name === saved)) apply(saved);
  }

  // DAG rails: hovering a row spotlights the rails feeding it (its
  // upstreams' rails) and the rail it sends downstream.
  document.querySelectorAll('svg.dag').forEach((svg) => {
    const rails = Array.from(svg.querySelectorAll('.rail'));
    if (!rails.length) return;
    svg.querySelectorAll('.dag-node[data-spec]').forEach((row) => {
      const mine = new Set((row.dataset.up || '').split(' ').filter(Boolean));
      mine.add(row.dataset.spec);
      row.addEventListener('mouseenter', () => {
        svg.classList.add('rails-hover');
        rails.forEach((r) => r.classList.toggle('hot', mine.has(r.dataset.src)));
      });
      row.addEventListener('mouseleave', () => {
        svg.classList.remove('rails-hover');
        rails.forEach((r) => r.classList.remove('hot'));
      });
    });
  });

  // Journal index: client-side text filter over the cards.
  const filterInput = document.getElementById('journal-filter-input');
  if (filterInput) {
    const cards = Array.from(document.querySelectorAll('.journal-card'));
    const count = document.getElementById('journal-filter-count');
    const apply = () => {
      const q = filterInput.value.trim().toLowerCase();
      let shown = 0;
      for (const c of cards) {
        const hit = !q || (c.dataset.search || '').includes(q);
        c.classList.toggle('is-hidden', !hit);
        if (hit) shown += 1;
      }
      if (count) count.textContent = shown + ' / ' + cards.length;
    };
    filterInput.addEventListener('input', apply);
    apply();
  }

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


_TEXT_SNIFF_BYTES = 8192

#: extension -> highlight.js language for the dev server's /view/ pages.
#: Unknown extensions fall back to plaintext — viewability is decided by
#: the byte sniff, never by this map.
_VIEW_LANGS = {
    ".csv": "plaintext", ".tsv": "plaintext", ".dat": "plaintext",
    ".log": "plaintext", ".txt": "plaintext",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "ini",
    ".md": "markdown", ".tex": "latex", ".py": "python", ".r": "r",
    ".jl": "julia", ".sh": "bash", ".sql": "sql",
    ".html": "xml", ".htm": "xml", ".xml": "xml", ".svg": "xml",
}


def output_lang(rel: str) -> str:
    """highlight.js language for an output path (plaintext when unknown)."""
    return _VIEW_LANGS.get(Path(rel).suffix.lower(), "plaintext")


#: suffixes the dev server serves as raw bytes — browsers render these
#: natively, so figures and PDFs are viewable without any recipe.
_RAW_VIEW_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf",
}


def raw_view_type(rel: str) -> str | None:
    """Content type for outputs served as raw bytes; None for the rest."""
    return _RAW_VIEW_TYPES.get(Path(rel).suffix.lower())


def is_text_file(path: Path) -> bool:
    """True when the leading bytes decode as UTF-8 with no NULs.

    A sniff, not a proof — it only decides whether the dashboard links
    an output chip and whether the dev server agrees to render the
    bytes as text."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(_TEXT_SNIFF_BYTES)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError as exc:
        # a char split at the sniff boundary is fine; garbage earlier is not
        return exc.start >= len(chunk) - 3
    return True


def _output_chip(root: Path, rel: str) -> str:
    """The output cell chip, linked to the dev server's /view/ page when
    the bytes are on disk and viewable: text renders escaped +
    highlighted, images and PDFs are served raw. Other binaries and
    remote bytes stay plain chips — there is nothing to open. From
    file:// there is no server either; the router JS strips these hrefs."""
    chip = f"<code>{_e(rel)}</code>"
    path = root / rel
    if path.is_file() and (raw_view_type(rel) or is_text_file(path)):
        return (
            f'<a class="output-link" href="/view/{_e(quote(rel))}" '
            f'target="_blank" title="view output">{chip}</a>'
        )
    return chip


#: badge word per axis state, reusing the status palette classes.
_CERT_CLASS = {
    Certification.UNIMPLEMENTED: "unimplemented",
    Certification.UNVOUCHED: "audit",
    Certification.REJECTED: "rejected",
    Certification.CERTIFIED: "ready",
}
_REAL_CLASS = {
    Realization.NEVER_RUN: "unimplemented",
    Realization.STALE: "stale",
    Realization.CURRENT: "ready",
}
#: sort keys: enum order is severity order (most broken first).
_CERT_RANK = {c: i for i, c in enumerate(Certification)}
_REAL_RANK = {r: i for i, r in enumerate(Realization)}


def _real_rank(r: Report) -> int:
    return _REAL_RANK[r.realization] if r.realization is not None else 9  # library last


def _cert_badge(r: Report) -> str:
    c = r.certification
    return f'<span class="badge {_CERT_CLASS[c]}">{_e(c.value)}</span>'


def _real_badge(r: Report) -> str:
    if r.realization is None:  # library: no run axis
        return '<span class="empty">—</span>'
    return f'<span class="badge {_REAL_CLASS[r.realization]}">{_e(r.realization.value)}</span>'


def _bytes_badge(report: Report) -> str:
    """A second chip when the claim stands but the bytes are elsewhere."""
    if report.materialized:
        return ""
    return (
        ' <span class="badge remote-bytes" title="claim recorded; outputs not on '
        'this disk — cache fetch materializes (verified)">bytes remote</span>'
    )


def _mind_hint(report: Report, project: Project) -> str:
    """Why this definition needs a mind (the vouch-axis diagnosis)."""
    if report.certification is Certification.UNIMPLEMENTED:
        return "no code at " + ", ".join(project.entries[report.entry].binding.scripts)
    if report.certification is Certification.UNVOUCHED:
        return "spec or code moved since vouch" if report.vouch else "never vouched"
    if report.certification is Certification.REJECTED and report.vouch is not None:
        v = report.vouch
        return f"rejected by {v.attester}" + (f": {v.note}" if v.note else "")
    return ""


def _machine_hint(report: Report) -> str:
    """Why this realization needs a machine (the run-axis diagnosis)."""
    if report.realization is Realization.NEVER_RUN:
        return "never run"
    if report.realization is Realization.STALE:
        return "moved: " + ", ".join(report.moved)
    return ""


def _entry_anchor(name: str) -> str:
    return f"entry-{name}"


def _spec_anchor(name: str) -> str:
    return f"spec-{name}"


def _journal_anchor(stem: str) -> str:
    return f"journal-{stem}"


def _entry_rows(spec: SpecFile, project: Project, reports: dict[str, Report]) -> str:
    rows = []
    for entry in spec.entries:
        r = reports.get(entry.name)
        if r is None:  # dormant under skip: true — no claims to show
            outputs = "<br>".join(_output_chip(project.root, o) for o in entry.outputs) or (
                '<span class="empty">—</span>'
            )
            rows.append(
                f'<tr id="{_e(_entry_anchor(entry.name))}">'
                f"<td><b>{_e(entry.name)}</b></td>"
                f'<td><span class="badge skipped">skipped</span></td>'
                f"<td>{outputs}</td>"
                f'<td><span class="empty">—</span></td>'
                f'<td><span class="empty">—</span></td></tr>'
            )
            continue
        if r.vouch:
            # Full note is a wall of text — keep the cell to verdict/attester/date
            # and stash the note in a hover tooltip.
            title = f' title="{_e(r.vouch.note)}"' if r.vouch.note else ""
            vouch = (
                f"<span{title}>{_e(r.vouch.verdict)} "
                f'<span class="who">by {_e(r.vouch.attester)}, '
                f"{_e(r.vouch.vouched[:10])}</span></span>"
            )
        else:
            vouch = '<span class="empty">—</span>'
        if r.run:
            run = f'<span class="who">{_e(r.run.ran[:10])} via {_e(r.run.executor)}</span>'
        else:
            run = '<span class="empty">—</span>'
        outputs = "<br>".join(_output_chip(project.root, o) for o in entry.outputs) or (
            '<span class="empty">code-only</span>'
        )
        moved = (
            f'<div class="moved">moved: {_e(", ".join(r.moved))}</div>'
            if r.moved and r.realization is Realization.STALE
            else ""
        )
        rows.append(
            f'<tr id="{_e(_entry_anchor(entry.name))}">'
            f"<td><b>{_e(entry.name)}</b></td>"
            f"<td>{_cert_badge(r)} {_real_badge(r)}{_bytes_badge(r)}{moved}</td>"
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


_MD_HREF = re.compile(r'href="(?!(?:[a-z][a-z0-9+.-]*:|//|#))([^"]+?\.md)(#[^"]*)?"')


def _rewrite_spec_links(
    rendered: str, spec_names: set[str], journal_stems: set[str] | None = None
) -> str:
    """Point markdown links at sibling specs/journal to their hash-routed section.

    Authors write ``[models](models.md)`` (or ``./models.md``,
    ``specs/models.md``) and ``[narrative](journal/2026-06-30-fix.md)``;
    in the single-page viewer those must become ``#spec-models`` /
    ``#journal-2026-06-30-fix`` or they 404. Links whose stem is neither
    a known spec nor a journal entry (external URLs, other repo files)
    are left untouched.
    """
    journal_stems = journal_stems or set()

    def repl(m: re.Match[str]) -> str:
        stem = Path(m.group(1)).stem
        if stem in spec_names:
            return f'href="#{_spec_anchor(stem)}"'
        if stem in journal_stems:
            return f'href="#{_journal_anchor(stem)}"'
        return m.group(0)

    return _MD_HREF.sub(repl, rendered)


def _worst_dot(spec: SpecFile, reports: dict[str, Report]) -> str:
    if spec.skip:
        return '<span class="dot dot-skip"></span>'
    rs = [reports[e.name] for e in spec.entries]
    if not rs:
        return ""
    if any(r.certification is not Certification.CERTIFIED or machine_repairable(r) for r in rs):
        return '<span class="dot dot-break"></span>'
    if any(not (r.computable and r.realized) for r in rs):
        return '<span class="dot dot-wait"></span>'
    return '<span class="dot dot-ready"></span>'


def _broken_files(project: Project, problems: list[Problem]) -> list[str]:
    """Problem files with no parsed SpecFile — they need their own sections."""
    parsed = {s.path.name for s in project.specs}
    return sorted({p.file for p in problems if p.file.endswith(".md") and p.file not in parsed})


def _spec_groups(project: Project) -> list[tuple[str, bool, list[SpecFile]]]:
    """Navigation order shared by the sidebar and the section stream.

    Custom ``group:`` blocks come first — a group ranks by the highest
    ``priority:`` among its specs (higher first, ties alphabetical) —
    then untagged specs keep today's kind blocks in ``_KIND_ORDER``.
    Within any block: priority desc, then name. The bool flags a
    custom group (its rows need a kind pill; kind headers don't).
    """
    custom: dict[str, list[SpecFile]] = {}
    by_kind: dict[str, list[SpecFile]] = {}
    for spec in project.specs:
        if spec.group:
            custom.setdefault(spec.group, []).append(spec)
        else:
            by_kind.setdefault(spec.kind, []).append(spec)

    def within(s: SpecFile) -> tuple[int, str]:
        return (-s.priority, s.name)

    ordered = [
        (label, True, sorted(custom[label], key=within))
        for label in sorted(
            custom, key=lambda g: (-max(s.priority for s in custom[g]), g.lower())
        )
    ]
    ordered += [
        (kind, False, sorted(by_kind[kind], key=within))
        for kind in sorted(by_kind, key=lambda k: _KIND_ORDER.get(k, 9))
    ]
    return ordered


def _pill(kind_class: str, label: str) -> str:
    """One icon pill: a ringed 10px stroke icon, full word in the tooltip."""
    return (
        f'<span class="pill {kind_class}" title="{_e(label)}">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICONS[label]}</svg></span>'
    )


def _nav_pills(spec: SpecFile, in_custom_group: bool) -> str:
    """Right-aligned icon pills for one sidebar row: the kind (only where
    the group header doesn't already say it) and the intensive tier."""
    pills = []
    if in_custom_group and spec.kind in ICONS:
        pills.append(_pill(f"kind-{_e(spec.kind)}", spec.kind))
    if spec.kind == "compute" and spec.tier == "intensive":
        pills.append(_pill("pill-tier", "intensive"))
    return f'<span class="pills">{"".join(pills)}</span>' if pills else ""


def _sidebar(
    project: Project,
    reports: dict[str, Report],
    problems: list[Problem],
    generated: str,
    journal: list[JournalEntry],
) -> str:
    broken = _broken_files(project, problems)
    problem_files = {p.file for p in problems}

    parts = [
        '<nav class="sidebar">',
        f"<h1>{_e(project.root.name)} &middot; specs/</h1>",
        f'<div class="meta-line">{len(project.specs) + len(broken)} files &middot; generated {_e(generated[:10])}</div>',
        '<div class="nav-group">'
        '<div class="nav-file" data-file-anchor="vouch">'
        '<a href="#vouch">Vouch tree</a></div>'
        '<div class="nav-file" data-file-anchor="run">'
        '<a href="#run">Run tree</a></div>'
        '<div class="nav-file" data-file-anchor="activity">'
        '<a href="#activity">Activity log</a></div></div>',
    ]
    if broken:
        parts.append(
            '<div class="nav-group"><div class="nav-group-header">'
            '<span class="kind kind-broken">does not parse</span></div>'
        )
        for filename in broken:
            anchor = _spec_anchor(Path(filename).stem)
            parts.append(
                f'<div class="nav-file" data-file-anchor="{_e(anchor)}">'
                f'<span class="dot dot-break"></span>'
                f'<a href="#{_e(anchor)}" title="{_e(filename)}">{_e(filename)}</a></div>'
            )
        parts.append("</div>")
    for label, is_custom, specs in _spec_groups(project):
        header_cls = "kind kind-custom" if is_custom else f"kind kind-{_e(label)}"
        parts.append(
            f'<div class="nav-group"><div class="nav-group-header">'
            f'<span class="{header_cls}">{_e(label)}</span></div>'
        )
        for spec in specs:
            anchor = _spec_anchor(spec.name)
            dot = (
                '<span class="dot dot-break"></span>'
                if spec.path.name in problem_files
                else _worst_dot(spec, reports)
            )
            skipped_cls = " skipped" if spec.skip else ""
            parts.append(
                f'<div class="nav-file{skipped_cls}" data-file-anchor="{_e(anchor)}">'
                f"{dot}"
                f'<a href="#{_e(anchor)}" title="{_e(spec.path.name)}">{_e(spec.title)}</a>'
                f"{_nav_pills(spec, is_custom)}</div>"
            )
        parts.append("</div>")
    if journal:
        parts.append(
            '<div class="nav-group nav-journal"><div class="nav-group-header">'
            '<span class="kind kind-journal">journal</span></div>'
            '<div class="nav-file" data-file-anchor="journal">'
            f'<a href="#journal">Journal</a> <span class="journal-date">({len(journal)})</span></div>'
        )
        for entry in journal:
            anchor = _journal_anchor(entry.stem)
            date = f'<span class="journal-date">{_e(entry.date)}</span>' if entry.date else ""
            parts.append(
                f'<div class="nav-file" data-file-anchor="{_e(anchor)}">'
                f'{date}<a href="#{_e(anchor)}" title="{_e(entry.path.name)}">'
                f"{_e(entry.title)}</a></div>"
            )
        parts.append("</div>")
    parts.append("</nav>")
    return "".join(parts)


def _problems_box(problems: list[Problem]) -> str:
    if not problems:
        return ""
    items = "".join(f"<li>{_e(p.message)}</li>" for p in problems)
    return (
        '<div class="warnings problems"><b>Spec problems</b> — grammar, '
        f"fix before trusting anything below (`specthis lint`):<ul>{items}</ul></div>"
    )


def _broken_section(root: Path, filename: str, problems: list[Problem]) -> str:
    """Best-effort page for a file that failed to parse: the errors, then
    the markdown rendered anyway (minus any frontmatter block)."""
    messages = "".join(f"<li>{_e(p.message)}</li>" for p in problems if p.file == filename)
    body_html = ""
    path = root / "specs" / filename
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER.match(text)
        rendered = _markdown.markdown(
            text[m.end():] if m else text, extensions=["tables", "fenced_code"]
        )
        body_html = f'<div class="md">{rendered}</div>'
    return (
        f'<section class="spec" id="{_e(_spec_anchor(Path(filename).stem))}">'
        f'<h2 class="spec-title">{_e(filename)}</h2>'
        f'<div class="warnings problems"><b>Does not parse</b><ul>{messages}</ul></div>'
        f"{body_html}</section>"
    )


def _why(r: Report, entry: Entry, project: Project, reports: dict[str, Report]) -> str:
    """One line of diagnosis for the detail card: the per-tree repair
    hints for local breaks, the blocking upstreams for a waiting entry."""
    parts = []
    hint = _mind_hint(r, project)
    if hint:
        parts.append(f"mind: {hint}")
    if machine_repairable(r):
        parts.append(f"machine: {_machine_hint(r)}")
    if parts:
        return "; ".join(parts)
    if not (r.computable and r.realized):
        broken = [
            u for u in entry.consumes if not (reports[u].computable and reports[u].realized)
        ]
        return "waiting on " + ", ".join(broken)
    return ""


def _detail_row(
    entry: Entry,
    r: Report,
    project: Project,
    reports: dict[str, Report],
    consumed_by: dict[str, list[str]],
) -> str:
    """The collapsed card under each dashboard row: diagnosis, the
    entry's direct DAG neighborhood, and the ledger facts."""

    def chips(names: list[str]) -> str:
        return " ".join(
            f'<a href="#{_e(_entry_anchor(n))}"><code>{_e(n)}</code></a>' for n in names
        ) or '<span class="empty">—</span>'

    lines: list[tuple[str, str]] = []
    why = _why(r, entry, project, reports)
    if why:
        lines.append(("why", _e(why)))
    lines.append(("consumes", chips(entry.consumes)))
    lines.append(("consumed by", chips(consumed_by.get(entry.name, []))))
    outputs = " ".join(_output_chip(project.root, o) for o in entry.outputs) or (
        '<span class="empty">code-only</span>'
    )
    lines.append(("outputs", outputs))
    if r.vouch:
        note = f" — {r.vouch.note}" if r.vouch.note else ""
        lines.append(
            (
                "vouch",
                f'{_e(r.vouch.verdict)} <span class="who">by {_e(r.vouch.attester)}, '
                f"{_e(r.vouch.vouched[:10])}{_e(note)}</span>",
            )
        )
    if r.run:
        lines.append(
            ("run", f'<span class="who">{_e(r.run.ran[:10])} via {_e(r.run.executor)}</span>')
        )
    if entry.binding.scripts:
        lines.append(
            ("scripts", " ".join(f"<code>{_e(s)}</code>" for s in entry.binding.scripts))
        )
    body = "".join(
        f'<div class="dep"><span class="lbl">{_e(label)}</span> {value}</div>'
        for label, value in lines
    )
    return f'<tr class="detail"><td colspan="9"><div class="detail-card">{body}</div></td></tr>'


def _cached_cell(r: Report, entry: Entry) -> str:
    """Cached column: where the claimed bytes are — a run-tree fact.
    ``disk`` when the standing claim's outputs are on this disk,
    ``remote`` when the claim stands but the bytes live in the cache
    (fetchable), em-dash when there are no outputs or no standing
    claim. Certification does not enter: an unvouched entry's bytes
    are still exactly where its run row says."""
    claim_stands = r.run is not None and r.realization is Realization.CURRENT and entry.outputs
    if not claim_stands:
        return '<td data-sort=""><span class="empty">—</span></td>'
    if not r.materialized:
        return (
            '<td data-sort="0"><span class="badge remote-bytes" '
            'title="claim recorded; outputs not on this disk — cache fetch '
            'materializes (verified)">remote</span></td>'
        )
    return '<td data-sort="1">disk</td>'


_EMPTY = '<span class="empty">—</span>'


def _kind_tier(e: Entry) -> str:
    """`library` bare (tier is meaningless there), `kind/tier` otherwise —
    on the run page the tier is the rebuild-cost signal next to `stale`."""
    return _e(e.spec.kind if e.spec.kind == "library" else f"{e.spec.kind}/{e.tier}")


def _chip_row(tallies: list[tuple[str, int]]) -> str:
    return "".join(
        f'<span class="chip"><b>{n}</b> {_e(label)}</span>' for label, n in tallies if n
    ) or '<span class="chip">no entries yet</span>'


def _stamp_cell(iso: str | None) -> str:
    """A date cell sorting by the full ISO stamp; em-dash without one."""
    if not iso:
        return f'<td data-sort="">{_EMPTY}</td>'
    return f'<td data-sort="{_e(iso)}" title="{_e(iso)}">{_e(iso[:10])}</td>'


def _took_cell(seconds: float | None) -> str:
    return f"<td>{_e(fmt_duration(seconds))}</td>" if seconds else f"<td>{_EMPTY}</td>"


def _vouch_section(
    project: Project,
    reports: dict[str, Report],
    problems: list[Problem],
) -> str:
    """The landing page: the vouch tree. Every definition's trust
    state with its judgment facts (who vouched, when, at what cost,
    what moved since), above the DAG — on this page rails AND dots
    speak the vouch axis. Run-tree facts live on the Run tree page."""
    rs = list(reports.values())
    ready = sum(1 for r in rs if r.computable and r.realized)
    tallies = [
        (c.value, sum(1 for r in rs if r.certification is c)) for c in Certification
    ] + [("ready", ready)]
    chips = _chip_row(tallies)
    if project.skipped_entries:
        chips += f'<span class="chip"><b>{len(project.skipped_entries)}</b> skipped</span>'

    consumed_by = _consumed_by(project)
    rows = []
    for name, e in sorted(project.entries.items()):
        r = reports[name]
        v = r.vouch
        expired = (
            f'<span class="who">{_e("; ".join(r.expired))}</span>' if r.expired else _EMPTY
        )
        rows.append(
            f'<tr class="entry-row" data-name="{_e(name)}" '
            f'data-consumes="{_e(" ".join(e.consumes))}">'
            '<td class="focus-cell"><button class="focus-btn" '
            'title="focus — show only its upstream/downstream">&#8982;</button>'
            '<span class="dir"></span></td>'
            f'<td><a href="#{_e(_entry_anchor(name))}"><b>{_e(name)}</b></a></td>'
            f'<td><a href="#{_e(_spec_anchor(e.spec.name))}">{_e(e.spec.name)}</a></td>'
            f"<td>{_kind_tier(e)}</td>"
            f'<td data-sort="{_CERT_RANK[r.certification]}">{_cert_badge(r)}</td>'
            f"<td>{_e(v.attester) if v else _EMPTY}</td>"
            f"{_stamp_cell(v.vouched if v else None)}"
            f"{_took_cell(v.duration_seconds if v else None)}"
            f"<td>{expired}</td></tr>"
            + _detail_row(e, r, project, reports, consumed_by)
        )
    focus_bar = (
        '<div class="focus-bar" id="focus-bar" hidden>'
        "<span>&#8982; focused on <b id=\"focus-name\"></b> "
        '<span class="who" id="focus-counts"></span></span>'
        '<button id="focus-clear">clear</button></div>'
    )
    table = (
        focus_bar
        + '<table class="sortable"><thead><tr><th class="no-sort"></th>'
        "<th>entry</th><th>spec</th><th>kind/tier</th><th>vouch state</th><th>by</th>"
        "<th>vouched</th><th>took</th><th>moved since vouch</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table>'
        if rows
        else '<p class="empty">No entries yet.</p>'
    )

    dag = dag_svg(project, reports, axis="vouch")
    if dag:
        dag += (
            '<div class="dag-caption">artefact flow (<code>consumes</code>): '
            "every spec sits below its inputs; rails and dots are vouch "
            "states — trust flows down. Run states live on the "
            '<a href="#run">Run tree</a> page &mdash; hover a row to trace '
            "it, click to open the spec</div>"
        )

    return (
        '<section class="spec" id="vouch">'
        '<h2 class="spec-title">Vouch tree</h2>'
        '<div class="spec-meta"><span class="who">the definitions — judged by '
        "minds; a vouch covers one (spec, code) pair and expires when either "
        "moves</span></div>"
        f'<div class="chips">{chips}</div>'
        f"{_problems_box(problems)}{dag}{table}</section>"
    )


def _run_section(project: Project, reports: dict[str, Report]) -> str:
    """The run tree: every realization's state with its ledger facts
    (when it ran, via what, at what cost, where the bytes are).
    Library entries have no run axis and do not appear."""
    rs = [r for r in reports.values() if r.realization is not None]
    ready = sum(1 for r in reports.values() if r.computable and r.realized)
    tallies = [(x.value, sum(1 for r in rs if r.realization is x)) for x in Realization]
    remote = sum(1 for r in rs if not r.materialized)
    tallies += [("bytes remote", remote), ("ready", ready)]
    chips = _chip_row(tallies)

    consumed_by = _consumed_by(project)
    rows = []
    for name, e in sorted(project.entries.items()):
        r = reports[name]
        if r.realization is None:  # library: the chain stops at code
            continue
        run = r.run
        moved = f'<span class="who">{_e(", ".join(r.moved))}</span>' if r.moved else _EMPTY
        rows.append(
            f'<tr class="entry-row" data-name="{_e(name)}">'
            f'<td><a href="#{_e(_entry_anchor(name))}"><b>{_e(name)}</b></a></td>'
            f'<td><a href="#{_e(_spec_anchor(e.spec.name))}">{_e(e.spec.name)}</a></td>'
            f"<td>{_kind_tier(e)}</td>"
            f'<td data-sort="{_real_rank(r)}">{_real_badge(r)}{_bytes_badge(r)}</td>'
            f"{_stamp_cell(run.ran if run else None)}"
            f"<td>{_e(run.executor) if run else _EMPTY}</td>"
            f"{_took_cell(run.duration_seconds if run else None)}"
            f"{_cached_cell(r, e)}"
            f"<td>{moved}</td></tr>"
            + _detail_row(e, r, project, reports, consumed_by)
        )
    table = (
        '<table class="sortable"><thead><tr>'
        "<th>entry</th><th>spec</th><th>kind/tier</th><th>run state</th><th>ran</th>"
        "<th>via</th><th>took</th><th>cached</th><th>moved</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table>'
        if rows
        else '<p class="empty">No runnable entries (libraries stop at code).</p>'
    )
    return (
        '<section class="spec" id="run">'
        '<h2 class="spec-title">Run tree</h2>'
        '<div class="spec-meta"><span class="who">the realizations — rebuilt by '
        "machines; a run claim pins exact input bytes to exact output bytes and "
        "goes stale when either moves</span></div>"
        f'<div class="chips">{chips}</div>'
        f"{table}</section>"
    )


def _spec_section(
    spec: SpecFile,
    project: Project,
    reports: dict[str, Report],
    journal_stems: set[str] | None = None,
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
    group = (
        f'&middot; <span class="kind kind-custom">{_e(spec.group)}</span> ' if spec.group else ""
    )
    skipped_badge = (
        ' <span class="badge skipped">skipped — entries dormant</span>' if spec.skip else ""
    )
    meta = (
        f'<div class="spec-meta"><span class="kind kind-{_e(spec.kind)}">{_e(spec.kind)}</span> '
        f"{tier} {group}<code>{_e(spec.path.name)}</code> {pair}{skipped_badge}</div>"
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

    body_html = ""
    if spec.body.strip():
        rendered = _markdown.markdown(spec.body, extensions=["tables", "fenced_code"])
        body_html = (
            f'<div class="md">{_rewrite_spec_links(rendered, spec_names, journal_stems)}</div>'
        )

    return (
        f'<section class="spec{" skipped" if spec.skip else ""}" '
        f'id="{_e(_spec_anchor(spec.name))}">'
        f'<h2 class="spec-title">{_e(spec.title)}</h2>{meta}'
        + "".join(deps)
        + _entry_rows(spec, project, reports)
        + body_html
        + "</section>"
    )


def _when_cell(iso: str, now: datetime) -> str:
    ago = fmt_ago(iso, now)
    return (
        f'<td data-sort="{_e(iso)}" title="{_e(iso)}">{_e(ago)} '
        f'<span class="who">{_e(iso[:10])}</span></td>'
    )


def _activity_section(
    reports: dict[str, Report],
    journal: list[JournalEntry],
    generated: str,
) -> str:
    """The activity log: every entry's current vouch and run, plus the
    journal, as one feed newest-first. The ledgers keep one row per
    entry (a re-vouch or re-run replaces the prior claim), so this is
    each entry's latest happening of each kind — not an append-only
    history."""
    now = datetime.fromisoformat(generated)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    empty = '<span class="empty">—</span>'
    events: list[tuple[str, str]] = []  # (ISO stamp — the sort key, <tr> html)
    for name, r in sorted(reports.items()):
        link = f'<a href="#{_e(_entry_anchor(name))}"><b>{_e(name)}</b></a>'
        if r.vouch:
            v = r.vouch
            badge = (
                '<span class="badge rejected">rejected</span>'
                if v.verdict == "rejected"
                else '<span class="badge evt-vouch">vouched ok</span>'
            )
            note = f' title="{_e(v.note)}"' if v.note else ""
            took = _e(fmt_duration(v.duration_seconds)) if v.duration_seconds else empty
            events.append(
                (
                    v.vouched,
                    f"<tr>{_when_cell(v.vouched, now)}<td{note}>{badge}</td>"
                    f"<td>{link}</td><td>{_e(v.attester)}</td><td>{took}</td></tr>",
                )
            )
        if r.run:
            took = _e(fmt_duration(r.run.duration_seconds)) if r.run.duration_seconds else empty
            events.append(
                (
                    r.run.ran,
                    f'<tr>{_when_cell(r.run.ran, now)}<td><span class="badge evt-run">ran</span></td>'
                    f"<td>{link}</td><td>{_e(r.run.executor)}</td><td>{took}</td></tr>",
                )
            )
    for j in journal:
        jlink = f'<a href="#{_e(_journal_anchor(j.stem))}">{_e(j.title)}</a>'
        when = _when_cell(j.date, now) if j.date else f'<td data-sort="">{empty}</td>'
        events.append(
            (
                j.date,
                f'<tr>{when}<td><span class="badge evt-journal">journal</span></td>'
                f"<td>{jlink}</td><td>{empty}</td><td>{empty}</td></tr>",
            )
        )
    events.sort(key=lambda e: e[0], reverse=True)
    table = (
        '<table class="sortable"><thead><tr><th>when</th><th>event</th>'
        "<th>what</th><th>by / via</th><th>took</th></tr></thead>"
        f'<tbody>{"".join(row for _, row in events)}</tbody></table>'
        if events
        else '<p class="empty">Nothing recorded yet.</p>'
    )
    return (
        '<section class="spec" id="activity">'
        '<h2 class="spec-title">Activity log</h2>'
        '<div class="spec-meta"><span class="who">each entry&#8217;s latest vouch and run '
        "(the ledgers keep the most recent claim per entry), plus the journal — "
        "newest first</span></div>"
        f"{table}</section>"
    )


def _journal_index_section(journal: list[JournalEntry]) -> str:
    """The filterable card grid over every journal entry, newest first."""
    cards = []
    for entry in journal:
        search = _e(f"{entry.date} {entry.stem} {entry.title}".lower())
        date = f'<span class="journal-card-date">{_e(entry.date)}</span>' if entry.date else ""
        cards.append(
            f'<a class="journal-card" href="#{_e(_journal_anchor(entry.stem))}" '
            f'data-search="{search}">{date}'
            f'<span class="journal-card-title">{_e(entry.title)}</span></a>'
        )
    return (
        '<section class="spec" id="journal">'
        '<h2 class="spec-title">Journal</h2>'
        '<div class="spec-meta"><span class="kind kind-journal">journal</span> '
        "<code>journal/</code></div>"
        '<div class="journal-filter">'
        '<input id="journal-filter-input" type="search" '
        'placeholder="filter entries&hellip;" autocomplete="off">'
        f'<span class="journal-filter-count" id="journal-filter-count">'
        f"{len(journal)} / {len(journal)}</span></div>"
        f'<div class="journal-cards">{"".join(cards)}</div></section>'
    )


def _journal_section(
    entry: JournalEntry, spec_names: set[str], journal_stems: set[str]
) -> str:
    date = f'<span class="journal-date">{_e(entry.date)}</span> ' if entry.date else ""
    meta = (
        '<div class="spec-meta"><span class="kind kind-journal">journal</span> '
        f"<code>journal/{_e(entry.path.name)}</code></div>"
    )
    body_html = ""
    if entry.body.strip():
        rendered = _markdown.markdown(entry.body, extensions=["tables", "fenced_code"])
        body_html = (
            f'<div class="md">{_rewrite_spec_links(rendered, spec_names, journal_stems)}</div>'
        )
    return (
        f'<section class="spec journal-entry" id="{_e(_journal_anchor(entry.stem))}">'
        f'<h2 class="spec-title">{date}{_e(entry.title)}</h2>{meta}{body_html}</section>'
    )


def render_html(
    project: Project,
    reports: dict[str, Report],
    generated: str,
    problems: list[Problem] | None = None,
    journal: list[JournalEntry] | None = None,
) -> str:
    problems = problems or []
    journal = journal or []
    spec_names = {s.name for s in project.specs}
    journal_stems = {j.stem for j in journal}
    sections = (
        [_vouch_section(project, reports, problems)]
        + [_run_section(project, reports)]
        + [_activity_section(reports, journal, generated)]
        + [
            _broken_section(project.root, filename, problems)
            for filename in _broken_files(project, problems)
        ]
        + [
            _spec_section(spec, project, reports, journal_stems)
            for _, _, specs in _spec_groups(project)
            for spec in specs
        ]
        + ([_journal_index_section(journal)] if journal else [])
        + [_journal_section(j, spec_names, journal_stems) for j in journal]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>specs/ &mdash; {_e(project.root.name)}</title>
<script>document.documentElement.classList.add('js-routed');</script>
<style>{_CSS}</style>
{_MATHJAX}</head>
<body><div class="layout">
{_sidebar(project, reports, problems, generated, journal)}
<main class="content">
{"".join(sections)}
</main></div>
<a class="back-to-status" href="#vouch">vouch tree</a>
<script>{_ROUTER_JS}</script></body></html>
"""


def render(project: Project, problems: list[Problem] | None = None) -> tuple[str, dict]:
    """One joined view: (specs.html text, _index.json data)."""
    reports = check_project(project)
    journal = load_journal(project.root)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        render_html(project, reports, generated, problems, journal),
        build_index(project, reports, journal),
    )


def write_artefacts(root: Path) -> list[Path]:
    """Render and write specs/specs.html + _index.json.

    Lenient: grammar problems land in the page, not on stderr."""
    project, problems = load_project_lenient(root)
    html_text, index = render(project, problems)
    targets = {
        project.specs_dir / "specs.html": html_text,
        project.specs_dir / "_index.json": json.dumps(index, indent=2) + "\n",
    }
    for path, content in targets.items():
        path.write_text(content, encoding="utf-8")
    # retired generated view — clear it from trees written by older versions
    (project.specs_dir / "_routing.json").unlink(missing_ok=True)
    return list(targets)
