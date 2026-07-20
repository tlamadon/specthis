"""Spec-level DAG views for the status dashboard and `specthis dag`.

The status table answers *which entry, what repair*; these views answer
*what feeds what*. One node per spec that participates in artefact flow
(the kinds with entries), one edge per spec-level projection of
``consumes:`` — ``references:`` is vocabulary and stays out of the
picture. Entries collapse to one dot per run state with a count
(thirty same-state entries are one dot, not a bar of thirty; library
entries show their vouch state — they have no run axis), so the
frontier reads as a boundary: green upstream, a break, its wake
downstream.

Two views share the graph pass:

- **rails** (the dashboard's view): a git-log-style list — one row per
  spec in *story order* (every spec below all of its inputs, directly
  below the inputs only it consumes; shared foundations float to the
  top, the final deliverable lands last, edgeless specs trail). Edges
  run as vertical rails in a left gutter, one lane per upstream shared
  by all its out-edges and colored by that upstream's vouch state —
  trust visibly flows down the page. Scales as a list: no horizontal
  scroll.
- **layered** (the figure, `specthis dag`'s default): a Sugiyama-lite
  node-link diagram — longest-path layering, a few barycenter sweeps —
  that shows the pipeline's shape at a glance. Top-down by default
  (rows pack nodes at natural label width); ``lr`` for left-to-right.

`specthis dag --format json` emits the graph with both placements
(layered geometry plus story order/lane), for re-rendering elsewhere.
Pure view code, no graph library; like the dashboard, all of it is a
regenerated view — nothing ever reads it back. Skipped specs render
greyed with their dormant edges. Only dormant edges can form a cycle
(live edges are validated and cycle-checked before any render); on a
cycle the dormant edges are dropped rather than the picture.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from html import escape

from .check import Certification, Realization, Report
from .icons import svg_icon
from .parse import ENTRY_KINDS, Project, SpecFile
from .timefmt import fmt_ago, fmt_duration

#: axis fills — the badge palette, saturated enough to read at dot
#: size. Rails and library dots speak the vouch axis; entry dots the
#: run axis. Entries without a report (dormant) use skip grey.
_CERT_FILL = {
    Certification.UNIMPLEMENTED: "#9a958c",
    Certification.UNVOUCHED: "#c06a1f",
    Certification.REJECTED: "#a40e26",
    Certification.CERTIFIED: "#4d9367",
}
_REAL_FILL = {
    Realization.NEVER_RUN: "#9a958c",
    Realization.STALE: "#c39117",
    Realization.CURRENT: "#4d9367",
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
#: gives the views, with the palette values resolved.
_STANDALONE_STYLE = (
    "<style>"
    'text { font: 600 12px -apple-system, "Segoe UI", Roboto, sans-serif; fill: #1a1a1a; }'
    " .cnt { font-size: 10px; fill: #5a5a5a; }"
    " .meta { font-size: 10px; font-weight: 400; fill: #8a857b; }"
    " .box { fill: #fff; stroke: #d8d4cc; stroke-width: 1.2; }"
    " .skipped { opacity: 0.55; }"
    " .skipped .box { stroke-dasharray: 4 3; }"
    " .edge { fill: none; stroke: #b9b3a7; stroke-width: 1.3; }"
    " .rail { fill: none; stroke-width: 2; stroke-linecap: round; opacity: 0.45; }"
    " .hit { fill: none; }"
    "</style>"
)

_NODE_H = 44
_H_GAP = 56  # layered lr: between columns — room for edges to bend readably
_V_GAP = 18  # layered lr: between nodes stacked in a column
_ROW_GAP = 52  # layered tb: between layer rows
_SIB_GAP = 26  # layered tb: between nodes side by side in a row
_RAILS_ROW_H = 30  # rails: one list row
_LANE_W = 14  # rails: gutter lane pitch
_PAD = 12

#: Rails is the dashboard default (a scanning list: no horizontal
#: scroll, labels aligned, trust flowing down the gutter); layered is
#: the `specthis dag` default (a figure: the pipeline's shape).
VIEWS = ("rails", "layered")

#: Layered top-down is the default orientation: node width (the label)
#: is the dominant dimension, and tb lets rows pack nodes at natural
#: width while lr forces every column as wide as its widest label.
ORIENTS = ("tb", "lr")


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


def _graph(
    project: Project,
) -> tuple[dict[str, SpecFile], list[tuple[str, str]], dict[str, int]] | None:
    """spec_graph plus layering, with the dormant-cycle fallback shared
    by every view; None when there is no flow to picture (isolated
    specs are already covered by the sidebar dots)."""
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
    return by_name, edges, layer


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


def _story_order(
    names: set[str], edges: list[tuple[str, str]], layer: dict[str, int]
) -> list[str]:
    """Rows for the rails view: post-order DFS up from the sinks.

    Every spec lands below all of its inputs; a spec's widely-consumed
    inputs are visited first so the inputs that exist only for it stay
    pinned directly above it. Shared foundations float to the top, the
    deepest deliverable lands last, edgeless specs trail at the bottom.
    Deterministic: ties break on (layer, name).
    """
    children: dict[str, list[str]] = {n: [] for n in names}
    parents: dict[str, list[str]] = {n: [] for n in names}
    for u, d in edges:
        children[u].append(d)
        parents[d].append(u)
    seen: set[str] = set()
    order: list[str] = []

    def visit(n: str) -> None:
        if n in seen:
            return
        seen.add(n)
        for p in sorted(parents[n], key=lambda p: (-len(children[p]), layer[p], p)):
            visit(p)
        order.append(n)

    sinks = sorted(
        (n for n in names if not children[n] and parents[n]),
        key=lambda n: (layer[n], n),
    )
    for n in [*sinks, *sorted(names)]:
        visit(n)
    return order


def _lanes(order: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Gutter lane per spec: its rail spans from its own row to its last
    consumer's row; smallest lane free over that interval (greedy
    interval coloring). All of an upstream's out-edges share its lane."""
    row = {n: i for i, n in enumerate(order)}
    children: dict[str, list[str]] = defaultdict(list)
    for u, d in edges:
        children[u].append(d)
    busy: dict[int, list[tuple[int, int]]] = defaultdict(list)
    lane: dict[str, int] = {}
    for n in order:
        s = row[n]
        e = max((row[c] for c in children[n]), default=s)
        k = 0
        while any(a <= e and s <= b for a, b in busy[k]):
            k += 1
        lane[n] = k
        busy[k].append((s, e))
    return lane


def _dot_groups(
    spec: SpecFile, reports: dict[str, Report], axis: str = "run"
) -> list[tuple[str, int, str, list[str]]]:
    """Entry dots collapsed per state: (label, count, fill, entry
    names), severity-ordered (most broken first, skipped last).
    ``axis="run"`` groups by run state (library entries have no run
    axis, so their vouch state stands in); ``axis="vouch"`` groups
    every entry by vouch state — the vouch-tree page's view. One dot
    per state keeps a spec with dozens of same-state entries from
    bloating into a bar of identical dots."""
    groups: dict[tuple[int, str, str], list[str]] = defaultdict(list)
    for entry in spec.entries:
        r = reports.get(entry.name)  # None when dormant under skip: true
        if r is None:
            key = (99, "skipped", _SKIP_FILL)
        elif axis == "vouch" or r.realization is None:
            c = r.certification
            key = (list(Certification).index(c), c.value, _CERT_FILL[c])
        else:
            x = r.realization
            key = (10 + list(Realization).index(x), x.value, _REAL_FILL[x])
        groups[key].append(entry.name)
    return [
        (label, len(names), fill, names)
        for (_, label, fill), names in sorted(groups.items())
    ]


def _rail_fill(spec: SpecFile, reports: dict[str, Report]) -> str:
    """Rail + origin-dot color: the spec's worst vouch state — trust is
    what flows down a rail, and trust is the vouch tree's word."""
    certs = [reports[e.name].certification for e in spec.entries if e.name in reports]
    if not certs:
        return _SKIP_FILL
    return _CERT_FILL[min(certs, key=list(Certification).index)]


def _group_advance(count: int) -> int:
    """Horizontal room one status-dot group takes: the dot, the count
    when there is more than one entry, and the gap to the next group."""
    return 8 + (3 + len(str(count)) * 7 if count > 1 else 0) + 10


def _dots_width(groups: list[tuple[str, int, str, list[str]]]) -> int:
    return sum(_group_advance(c) for _, c, _, _ in groups) - (10 if groups else 0)


def _node_width(name: str, groups: list[tuple[str, int, str, list[str]]]) -> int:
    # 26 = icon gutter before the label; the box must hold label and dots
    return int(max(80, 38 + len(name) * 7.2, 24 + _dots_width(groups)))


def _chips(
    groups: list[tuple[str, int, str, list[str]]], cy: int
) -> str:
    """The per-status dot groups, laid out left to right around ``cy``;
    each group's tooltip names its entries."""
    parts = []
    cx = 0
    for label, count, fill, entry_names in groups:
        tip = f"{label} ({count}): {', '.join(entry_names)}"
        cnt = (
            f'<text class="cnt" x="{cx + 11}" y="{cy + 4}">{count}</text>' if count > 1 else ""
        )
        parts.append(
            f"<g><title>{escape(tip)}</title>"
            f'<circle cx="{cx + 4}" cy="{cy}" r="4" fill="{fill}"/>{cnt}</g>'
        )
        cx += _group_advance(count)
    return "".join(parts)


def _entry_timing(r: Report) -> str:
    """One entry's ledger timing: ``ran 2h ago (3m 12s) · vouched 3d ago``.
    Durations appear when the row recorded one; "" without any claim."""
    parts = []
    if r.run is not None:
        took = f" ({fmt_duration(r.run.duration_seconds)})" if r.run.duration_seconds else ""
        parts.append(f"ran {fmt_ago(r.run.ran)}{took}")
    if r.vouch is not None:
        took = (
            f" ({fmt_duration(r.vouch.duration_seconds)})" if r.vouch.duration_seconds else ""
        )
        parts.append(f"vouched {fmt_ago(r.vouch.vouched)}{took}")
    return " · ".join(p for p in parts if p)


def _spec_timing(spec: SpecFile, reports: dict[str, Report]) -> str:
    """The spec-level timing line for the rails row: the most recent run
    and most recent vouch across the spec's entries, each with its own
    duration. Per-entry detail lives in the tooltip."""
    rs = [reports[e.name] for e in spec.entries if e.name in reports]
    latest_run = max((r.run for r in rs if r.run), key=lambda x: x.ran, default=None)
    latest_vouch = max((r.vouch for r in rs if r.vouch), key=lambda x: x.vouched, default=None)
    parts = []
    if latest_run is not None:
        took = (
            f" ({fmt_duration(latest_run.duration_seconds)})"
            if latest_run.duration_seconds
            else ""
        )
        parts.append(f"ran {fmt_ago(latest_run.ran)}{took}")
    if latest_vouch is not None:
        took = (
            f" ({fmt_duration(latest_vouch.duration_seconds)})"
            if latest_vouch.duration_seconds
            else ""
        )
        parts.append(f"vouched {fmt_ago(latest_vouch.vouched)}{took}")
    return " · ".join(p for p in parts if p)


def _summary(
    spec: SpecFile,
    groups: list[tuple[str, int, str, list[str]]],
    reports: dict[str, Report],
) -> str:
    counts = ", ".join(f"{count} {label}" for label, count, _, _ in groups)
    lines = [f"{spec.path.name} — {counts or spec.kind}"]
    for entry in spec.entries:
        r = reports.get(entry.name)
        timing = _entry_timing(r) if r else ""
        if timing:
            lines.append(f"{entry.name}: {timing}")
    return escape("\n".join(lines))


@dataclass
class _Node:
    """One placed spec: identity from the spec, geometry from the layout."""

    spec: SpecFile
    x: int
    y: int
    width: int
    layer: int  # depth along the flow
    row: int  # index within the layer after crossing reduction


def _layout(
    project: Project, reports: dict[str, Report], orient: str
) -> tuple[list[_Node], list[tuple[str, str]], int, int] | None:
    """Layered placement: nodes, drawable edges, and (width, height) of
    the canvas; None when there is no flow to picture."""
    g = _graph(project)
    if g is None:
        return None
    by_name, edges, layer = g
    names = set(by_name)
    cols = _columns(names, edges, layer)
    widths = {n: _node_width(n, _dot_groups(s, reports)) for n, s in by_name.items()}
    placed: list[_Node] = []
    if orient == "lr":
        col_w = [max(widths[n] for n in col) for col in cols]
        col_x: list[int] = []
        x = _PAD
        for w in col_w:
            col_x.append(x)
            x += w + _H_GAP
        total_w = x - _H_GAP + _PAD
        col_h = [len(col) * _NODE_H + (len(col) - 1) * _V_GAP for col in cols]
        total_h = max(col_h) + 2 * _PAD
        for i, col in enumerate(cols):
            y = _PAD + (max(col_h) - col_h[i]) // 2  # center each column vertically
            for j, n in enumerate(col):
                placed.append(
                    _Node(by_name[n], col_x[i] + (col_w[i] - widths[n]) // 2, y, widths[n], i, j)
                )
                y += _NODE_H + _V_GAP
    else:  # tb — rows pack nodes at natural width; no column inflation
        row_w = [sum(widths[n] for n in col) + _SIB_GAP * (len(col) - 1) for col in cols]
        total_w = max(row_w) + 2 * _PAD
        total_h = len(cols) * _NODE_H + (len(cols) - 1) * _ROW_GAP + 2 * _PAD
        for i, col in enumerate(cols):
            x = _PAD + (max(row_w) - row_w[i]) // 2  # center each row
            y = _PAD + i * (_NODE_H + _ROW_GAP)
            for j, n in enumerate(col):
                placed.append(_Node(by_name[n], x, y, widths[n], i, j))
                x += widths[n] + _SIB_GAP
    return placed, edges, total_w, total_h


def dag_svg(
    project: Project,
    reports: dict[str, Report],
    orient: str = "tb",
    view: str = "rails",
    axis: str = "run",
) -> str:
    """The dashboard block — rails by default, the scanning view. "" when
    there is no flow to picture. ``axis`` picks what the entry dots
    speak (rails always speak the vouch axis)."""
    if view == "rails":
        svg = _render_rails(project, reports, standalone=False, axis=axis)
    else:
        svg = _render_layered(project, reports, standalone=False, orient=orient, axis=axis)
    return f'<div class="dag-wrap">{svg}</div>' if svg else ""


def dag_standalone_svg(
    project: Project, reports: dict[str, Report], orient: str = "tb", view: str = "layered"
) -> str:
    """A self-contained SVG document (`specthis dag`) — layered by
    default, the figure. Styles inlined, no page anchors. "" when there
    is no flow."""
    if view == "rails":
        svg = _render_rails(project, reports, standalone=True)
    else:
        svg = _render_layered(project, reports, standalone=True, orient=orient)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{svg}\n' if svg else ""


def _entry_json(name: str, reports: dict[str, Report]) -> dict:
    """One entry for ``dag_json``: status plus raw ledger timing (ISO
    timestamps and seconds; null when the claim or duration is absent)
    — re-renderers compute their own ages."""
    r = reports.get(name)
    run = r.run if r else None
    vouch = r.vouch if r else None
    return {
        "name": name,
        "status": r.status.value if r else "skipped",
        "certification": r.certification.value if r else None,
        "realization": r.realization.value if r and r.realization else None,
        "ran": run.ran if run else None,
        "run_seconds": run.duration_seconds if run else None,
        "vouched": vouch.vouched if vouch else None,
        "vouch_seconds": vouch.duration_seconds if vouch else None,
    }


def dag_json(
    project: Project, reports: dict[str, Report], orient: str = "tb"
) -> dict | None:
    """The same picture as data (`specthis dag --format json`): nodes
    carrying identity (spec, kind, entry statuses) and both computed
    placements — the layered layout (layer/row plus pixel geometry for
    the requested orient) and the rails placement (story-order index
    and gutter lane) — plus the edges and the layered canvas size.
    Enough to re-render either view with different aesthetics, or to
    ignore the placements and lay out the raw graph yourself. None
    when there is no flow."""
    laid = _layout(project, reports, orient)
    if laid is None:
        return None
    placed, edges, total_w, total_h = laid
    layer_map = {p.spec.name: p.layer for p in placed}
    story = _story_order(set(layer_map), edges, layer_map)
    story_row = {n: i for i, n in enumerate(story)}
    lanes = _lanes(story, edges)
    return {
        "orient": orient,
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
                "order": story_row[p.spec.name],
                "lane": lanes[p.spec.name],
                "entries": [_entry_json(e.name, reports) for e in p.spec.entries],
            }
            for p in placed
        ],
        "edges": [{"upstream": u, "downstream": d} for u, d in edges],
    }


def _render_layered(
    project: Project,
    reports: dict[str, Report],
    standalone: bool,
    orient: str,
    axis: str = "run",
) -> str:
    laid = _layout(project, reports, orient)
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
        if orient == "lr":  # right edge of upstream -> left edge of downstream
            x1 = xy[u][0] + widths[u]
            y1 = xy[u][1] + _NODE_H // 2
            x2, y2 = xy[d][0] - 2, xy[d][1] + _NODE_H // 2
            mid = (x1 + x2) // 2
            path = f"M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}"
        else:  # tb: bottom center of upstream -> top center of downstream
            x1 = xy[u][0] + widths[u] // 2
            y1 = xy[u][1] + _NODE_H
            x2, y2 = xy[d][0] + widths[d] // 2, xy[d][1] - 2
            mid = (y1 + y2) // 2
            path = f"M{x1},{y1} C{x1},{mid} {x2},{mid} {x2},{y2}"
        parts.append(
            f'<path class="edge" d="{path}" marker-end="url(#dag-arrow)"/>'
        )
    for p in placed:
        spec = p.spec
        groups = _dot_groups(spec, reports, axis)
        node = (
            f'<g class="dag-node{" skipped" if spec.skip else ""}" '
            f'transform="translate({p.x},{p.y})" data-spec="{escape(spec.name)}">'
            f"<title>{_summary(spec, groups, reports)}</title>"
            f'<rect class="box" width="{p.width}" height="{_NODE_H}" rx="6"/>'
            f"{svg_icon(spec.kind, 10, 8, 12, _KIND_FILL.get(spec.kind, '#6e6e6e'))}"
            f'<text x="26" y="19">{escape(spec.name)}</text>'
            f'<g transform="translate(12,0)">{_chips(groups, 30)}</g>'
            "</g>"
        )
        if not standalone:
            # anchor matches export's _spec_anchor — the hash router takes over
            node = f'<a href="#spec-{escape(spec.name)}">{node}</a>'
        parts.append(node)
    parts.append("</svg>")
    return "".join(parts)


def _render_rails(
    project: Project, reports: dict[str, Report], standalone: bool, axis: str = "run"
) -> str:
    """The git-log-style list. Rails render under the rows: one spine
    per upstream down its lane, a curve branching into each consumer's
    row. Rows carry data-spec/data-up so the page JS can spotlight a
    hovered row's rails."""
    g = _graph(project)
    if g is None:
        return ""
    by_name, edges, layer = g
    names = set(by_name)
    order = _story_order(names, edges, layer)
    lane = _lanes(order, edges)
    row = {n: i for i, n in enumerate(order)}
    children: dict[str, list[str]] = defaultdict(list)
    ups: dict[str, list[str]] = defaultdict(list)
    for u, d in edges:
        children[u].append(d)
        ups[d].append(u)

    groups = {n: _dot_groups(by_name[n], reports, axis) for n in order}
    timing = {n: _spec_timing(by_name[n], reports) for n in order}
    label_x = (max(lane.values()) + 1) * _LANE_W + _PAD + 20
    total_w = int(
        max(
            label_x
            + len(n) * 7.2
            + 14
            + _dots_width(groups[n])
            + (len(timing[n]) * 6.0 + 16 if timing[n] else 0)
            + _PAD
            for n in order
        )
    )
    total_h = len(order) * _RAILS_ROW_H + 2 * _PAD

    def lx(n: str) -> int:
        return _PAD + lane[n] * _LANE_W + _LANE_W // 2

    def cy(n: str) -> int:
        return _PAD + row[n] * _RAILS_ROW_H + _RAILS_ROW_H // 2

    parts = [
        f'<svg class="dag" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {total_w} {total_h}" '
        f'width="{total_w}" height="{total_h}" role="img" '
        'aria-label="spec dependency rails">',
    ]
    if standalone:
        parts.append(_STANDALONE_STYLE + '<rect width="100%" height="100%" fill="#fdfdfc"/>')
    for u in order:  # rails first, under the rows
        kids = children[u]
        if not kids:
            continue
        color = _rail_fill(by_name[u], reports)  # trust: the vouch axis
        x = lx(u)
        parts.append(
            f'<path class="rail" data-src="{escape(u)}" stroke="{color}" '
            f'd="M{x},{cy(u) + 5} V{max(cy(c) for c in kids) - 6}"/>'
        )
        for c in kids:
            tx = lx(c) - 5
            bend = min(x + _LANE_W, tx)
            parts.append(
                f'<path class="rail" data-src="{escape(u)}" stroke="{color}" '
                f'd="M{x},{cy(c) - _RAILS_ROW_H // 2} C{x},{cy(c)} {x},{cy(c)} '
                f'{bend},{cy(c)} H{tx}"/>'
            )
    mid = _RAILS_ROW_H // 2
    for n in order:
        spec = by_name[n]
        worst_fill = _rail_fill(spec, reports)  # the rail's origin speaks trust too
        chips_x = int(label_x + len(n) * 7.2 + 14)
        meta = (
            f'<text class="meta" x="{chips_x + _dots_width(groups[n]) + 16}" '
            f'y="{mid + 4}">{escape(timing[n])}</text>'
            if timing[n]
            else ""
        )
        node = (
            f'<g class="dag-node{" skipped" if spec.skip else ""}" '
            f'transform="translate(0,{cy(n) - mid})" data-spec="{escape(n)}" '
            f'data-up="{escape(" ".join(sorted(ups[n])))}">'
            f"<title>{_summary(spec, groups[n], reports)}</title>"
            f'<rect class="hit" width="{total_w}" height="{_RAILS_ROW_H}"/>'
            f'<circle cx="{lx(n)}" cy="{mid}" r="4.5" fill="{worst_fill}" '
            'stroke="#fdfdfc" stroke-width="1.5"/>'
            f"{svg_icon(spec.kind, label_x - 16, mid - 6, 12, _KIND_FILL.get(spec.kind, '#6e6e6e'))}"
            f'<text x="{label_x}" y="{mid + 4}">{escape(n)}</text>'
            f'<g transform="translate({chips_x},{mid})">'
            f"{_chips(groups[n], 0)}</g>"
            f"{meta}"
            "</g>"
        )
        if not standalone:
            node = f'<a href="#spec-{escape(n)}">{node}</a>'
        parts.append(node)
    parts.append("</svg>")
    return "".join(parts)
