"""Spec-level DAG overview for the status dashboard: layout + inline SVG.

The status table answers *which entry, what repair*; this strip answers
*what feeds what*. One node per spec that participates in artefact flow
(the kinds with entries), one edge per spec-level projection of
``consumes:`` — ``references:`` is vocabulary and stays out of the
picture. Inside each node, one dot per entry colored by derived status,
so the frontier reads as a boundary in the graph: green upstream, a
break, its wake downstream. Clicking a node opens the spec's section.

Pure view code, no graph library: layering is longest-path over the
consumes DAG, crossing reduction is a few barycenter sweeps — plenty at
project scale (tens of specs), and it keeps the page dependency-free.
Skipped specs render greyed with their dormant edges. Only dormant
edges can form a cycle (live edges are validated and cycle-checked
before any render); on a cycle the dormant edges are dropped rather
than the picture.

Three outputs of the same picture, all fed by one layout pass: the
dashboard strip (styled by the page CSS, nodes link into the spec
sections), a standalone SVG document for `specthis dag` (styles
inlined, no anchors — a portable snapshot you can mail, commit, or
drop into slides), and layout JSON for `specthis dag --format json`
(nodes with statuses, layer/row, pixel geometry; edges; canvas size)
for re-rendering with different aesthetics elsewhere. Like the
dashboard these are regenerated views: nothing ever reads them back.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from html import escape

from .check import Report, Status
from .parse import ENTRY_KINDS, Project, SpecFile

#: entry-dot fill per status — the badge palette, saturated enough to
#: read at dot size. Entries without a report (dormant) use skip grey.
_DOT_FILL = {
    Status.READY: "#4d9367",
    Status.STALE: "#c39117",
    Status.AUDIT_NEEDED: "#c06a1f",
    Status.REJECTED: "#a40e26",
    Status.UNIMPLEMENTED: "#9a958c",
    Status.UPSTREAM_UNVERIFIED: "#4a7fb5",
}
_SKIP_FILL = "#b9b3a7"

#: kind accent hexes — mirror the --kind-* vars in export._CSS so the
#: standalone document matches the page.
_KIND_FILL = {
    "meta": "#6e6e6e",
    "definitions": "#2e7d5b",
    "templates": "#6a3d8a",
    "compute": "#2e6e9e",
    "report": "#b85a1e",
    "library": "#8a6d1f",
}

#: inline rules for the standalone document — the look the page CSS
#: gives the strip, with the palette values resolved.
_STANDALONE_STYLE = (
    "<style>"
    'text { font: 600 12px -apple-system, "Segoe UI", Roboto, sans-serif; fill: #1a1a1a; }'
    " .box { fill: #fff; stroke: #d8d4cc; stroke-width: 1.2; }"
    " .skipped { opacity: 0.55; }"
    " .skipped .box { stroke-dasharray: 4 3; }"
    " .edge { fill: none; stroke: #b9b3a7; stroke-width: 1.3; }"
    "</style>"
)

_NODE_H = 44
_H_GAP = 56  # between columns — room for edges to bend readably
_V_GAP = 18
_PAD = 12


def spec_graph(project: Project) -> tuple[list[SpecFile], list[tuple[str, str]]]:
    """The spec-level projection: nodes (specs with entries, skipped
    included) and deduped ``consumes`` edges as (upstream, downstream).

    ``consumes:`` targets entry names, but the field lives on the spec
    and every entry inherits it — so the projection loses nothing.
    Skipped specs keep their dormant edges; targets that resolve to no
    known entry (possible only on skipped specs — live edges are
    validated at load) are silently not drawn.
    """
    nodes = [s for s in project.specs if s.kind in ENTRY_KINDS]
    names = {s.name for s in nodes}
    owner: dict[str, str] = {}
    for spec in nodes:
        for entry in spec.entries:
            owner.setdefault(entry.name, spec.name)
    edges: list[tuple[str, str]] = []
    for spec in nodes:
        for consumed in spec.consumes:
            up = owner.get(consumed)
            edge = (up or "", spec.name)
            if up and up != spec.name and up in names and edge not in edges:
                edges.append(edge)
    return nodes, edges


def _layers(names: set[str], edges: list[tuple[str, str]]) -> dict[str, int] | None:
    """Layer = longest consume-path from a source; None on a cycle."""
    ups: dict[str, list[str]] = {n: [] for n in names}
    for u, d in edges:
        ups[d].append(u)
    layer: dict[str, int] = {}
    try:
        for n in TopologicalSorter(ups).static_order():
            layer[n] = max((layer[u] + 1 for u in ups[n]), default=0)
    except CycleError:
        return None
    return layer


def _columns(
    names: set[str], edges: list[tuple[str, str]], layer: dict[str, int]
) -> list[list[str]]:
    """Nodes per layer, barycenter-swept to reduce edge crossings.

    Sweeps order each column by the mean fractional position of its
    neighbors in the columns already swept — which also handles edges
    that span several layers, so no dummy nodes are needed.
    """
    depth = max(layer.values()) + 1
    cols = [sorted(n for n in names if layer[n] == i) for i in range(depth)]
    ups: dict[str, list[str]] = defaultdict(list)
    downs: dict[str, list[str]] = defaultdict(list)
    for u, d in edges:
        ups[d].append(u)
        downs[u].append(d)

    def frac(col: list[str]) -> dict[str, float]:
        return {n: (j / (len(col) - 1) if len(col) > 1 else 0.5) for j, n in enumerate(col)}

    for swp in range(3):  # forward, backward, forward
        forward = swp % 2 == 0
        neigh = ups if forward else downs
        pos: dict[str, float] = {}
        for col in cols if forward else reversed(cols):
            cur = frac(col)
            if pos:
                col.sort(
                    key=lambda n: (
                        sum(pos[m] for m in neigh[n] if m in pos)
                        / max(sum(1 for m in neigh[n] if m in pos), 1)
                        if any(m in pos for m in neigh[n])
                        else cur[n],
                        n,
                    )
                )
            pos.update(frac(col))
    return cols


def _node_width(name: str, n_dots: int) -> int:
    return int(max(76, 24 + len(name) * 7.2, 24 + n_dots * 13))


@dataclass
class _Node:
    """One placed spec: identity from the spec, geometry from the layout."""

    spec: SpecFile
    x: int
    y: int
    width: int
    layer: int  # column index (depth along the flow)
    row: int  # index within the column after crossing reduction


def _layout(
    project: Project,
) -> tuple[list[_Node], list[tuple[str, str]], int, int] | None:
    """Placed nodes, drawable edges, and (width, height) of the canvas;
    None when there is no flow to picture."""
    nodes, edges = spec_graph(project)
    if not edges:
        return None
    by_name = {s.name: s for s in nodes}
    names = set(by_name)
    layer = _layers(names, edges)
    if layer is None:  # a dormant cycle — drop skipped specs' edges, keep the picture
        edges = [(u, d) for u, d in edges if not by_name[d].skip]
        layer = _layers(names, edges)
        if layer is None or not edges:
            return None

    cols = _columns(names, edges, layer)
    widths = {s.name: _node_width(s.name, len(s.entries)) for s in nodes}
    col_w = [max(widths[n] for n in col) for col in cols]
    col_x: list[int] = []
    x = _PAD
    for w in col_w:
        col_x.append(x)
        x += w + _H_GAP
    total_w = x - _H_GAP + _PAD
    col_h = [len(col) * _NODE_H + (len(col) - 1) * _V_GAP for col in cols]
    total_h = max(col_h) + 2 * _PAD
    placed: list[_Node] = []
    for i, col in enumerate(cols):
        y = _PAD + (max(col_h) - col_h[i]) // 2  # center each column vertically
        for j, n in enumerate(col):
            placed.append(
                _Node(by_name[n], col_x[i] + (col_w[i] - widths[n]) // 2, y, widths[n], i, j)
            )
            y += _NODE_H + _V_GAP
    return placed, edges, total_w, total_h


def dag_svg(project: Project, reports: dict[str, Report]) -> str:
    """The dashboard strip, or "" when there is no flow to picture
    (isolated specs are already covered by the sidebar dots)."""
    svg = _render(project, reports, standalone=False)
    return f'<div class="dag-wrap">{svg}</div>' if svg else ""


def dag_standalone_svg(project: Project, reports: dict[str, Report]) -> str:
    """The same picture as a self-contained SVG document (`specthis
    dag`): styles inlined, no page anchors. "" when there is no flow."""
    svg = _render(project, reports, standalone=True)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{svg}\n' if svg else ""


def dag_json(project: Project, reports: dict[str, Report]) -> dict | None:
    """The same picture as data (`specthis dag --format json`): nodes
    carrying identity (spec, kind, entry statuses) and the computed
    layout (layer/row plus pixel geometry), the edges, and the canvas
    size — enough to re-render with different aesthetics, or to ignore
    the geometry and lay out the raw graph yourself. None when there
    is no flow."""
    laid = _layout(project)
    if laid is None:
        return None
    placed, edges, total_w, total_h = laid
    return {
        "size": {"width": total_w, "height": total_h},
        "nodes": [
            {
                "spec": p.spec.name,
                "file": p.spec.path.name,
                "title": p.spec.title,
                "kind": p.spec.kind,
                "skip": p.spec.skip,
                "layer": p.layer,
                "row": p.row,
                "x": p.x,
                "y": p.y,
                "width": p.width,
                "height": _NODE_H,
                "entries": [
                    {
                        "name": e.name,
                        "status": (
                            reports[e.name].status.value if e.name in reports else "skipped"
                        ),
                    }
                    for e in p.spec.entries
                ],
            }
            for p in placed
        ],
        "edges": [{"upstream": u, "downstream": d} for u, d in edges],
    }


def _render(project: Project, reports: dict[str, Report], standalone: bool) -> str:
    laid = _layout(project)
    if laid is None:
        return ""
    placed, edges, total_w, total_h = laid
    xy = {p.spec.name: (p.x, p.y) for p in placed}
    widths = {p.spec.name: p.width for p in placed}

    parts = [
        f'<svg class="dag" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {total_w} {total_h}" '
        f'width="{total_w}" height="{total_h}" role="img" '
        'aria-label="spec dependency graph">',
        '<defs><marker id="dag-arrow" viewBox="0 0 8 8" refX="7" refY="4" '
        'markerWidth="6.5" markerHeight="6.5" orient="auto">'
        '<path d="M0.5,0.5 L7.5,4 L0.5,7.5 z" fill="#b9b3a7"/></marker></defs>',
    ]
    if standalone:
        parts.insert(1, _STANDALONE_STYLE + '<rect width="100%" height="100%" fill="#fdfdfc"/>')
    for u, d in edges:
        x1 = xy[u][0] + widths[u]
        y1 = xy[u][1] + _NODE_H // 2
        x2, y2 = xy[d][0] - 2, xy[d][1] + _NODE_H // 2
        mid = (x1 + x2) // 2
        parts.append(
            f'<path class="edge" d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}" '
            'marker-end="url(#dag-arrow)"/>'
        )
    for p in placed:
        spec = p.spec
        nx, ny = p.x, p.y
        dots, tips = [], []
        for j, entry in enumerate(spec.entries):
            r = reports.get(entry.name)  # None when dormant under skip: true
            label = f"{entry.name}: {r.status.value if r else 'skipped'}"
            tips.append(label)
            dots.append(
                f'<circle cx="{16 + j * 13}" cy="30" r="4" '
                f'fill="{_DOT_FILL[r.status] if r else _SKIP_FILL}">'
                f"<title>{escape(label)}</title></circle>"
            )
        title = escape(f"{spec.path.name} — {'; '.join(tips) if tips else spec.kind}")
        node = (
            f'<g class="dag-node{" skipped" if spec.skip else ""}" '
            f'transform="translate({nx},{ny})" data-spec="{escape(spec.name)}">'
            f"<title>{title}</title>"
            f'<rect class="box" width="{p.width}" height="{_NODE_H}" rx="6"/>'
            f'<rect x="0" y="6" width="3" height="{_NODE_H - 12}" rx="1.5" '
            f'fill="{_KIND_FILL.get(spec.kind, "#6e6e6e")}"/>'
            f'<text x="12" y="19">{escape(spec.name)}</text>' + "".join(dots) + "</g>"
        )
        if not standalone:
            # anchor matches export's _spec_anchor — the hash router takes over
            node = f'<a href="#spec-{escape(spec.name)}">{node}</a>'
        parts.append(node)
    parts.append("</svg>")
    return "".join(parts)
