"""The status page's spec-level DAG strip: projection, layout, rendering."""

from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner

from specthis.check import check_project
from specthis.cli import main
from specthis.dag import dag_json, dag_svg, spec_graph
from specthis.export import render
from specthis.parse import load_project, load_project_lenient

from .conftest import COMPUTE_ALPHA, MODELS, make_ready, write


def _svg(page: str) -> str:
    assert '<svg class="dag"' in page
    return page[page.index('<svg class="dag"'): page.index("</svg>")]


def _node_x(svg: str) -> dict[str, int]:
    return {
        m.group(2): int(m.group(1))
        for m in re.finditer(r'transform="translate\((\d+),\d+\)" data-spec="([^"]+)"', svg)
    }


def test_spec_graph_projects_consumes_to_spec_level(root: Path) -> None:
    nodes, edges = spec_graph(load_project(root))
    # models (definitions) carries no entries — not part of artefact flow
    assert {s.name for s in nodes} == {"compute-alpha", "compute-beta", "report-beta"}
    assert set(edges) == {
        ("compute-alpha", "compute-beta"),
        ("compute-beta", "report-beta"),
    }


def test_dag_renders_layered_left_to_right(root: Path) -> None:
    make_ready(root)
    page, _ = render(load_project(root))
    svg = _svg(page)
    x = _node_x(svg)
    assert x["compute-alpha"] < x["compute-beta"] < x["report-beta"]
    assert svg.count('class="edge"') == 2
    assert 'href="#spec-compute-beta"' in svg  # nodes click through to the spec


def test_dag_dots_follow_status(root: Path) -> None:
    # nothing vouched yet: code exists, so every entry is audit-needed
    svg = _svg(render(load_project(root))[0])
    assert svg.count('fill="#c06a1f"') == 3
    assert "<title>fit-alpha: audit needed</title>" in svg
    make_ready(root)
    svg = _svg(render(load_project(root))[0])
    assert svg.count('fill="#4d9367"') == 3


def test_dag_omitted_when_no_flow(tmp_path: Path) -> None:
    write(tmp_path, "specs/compute-alpha.md", COMPUTE_ALPHA)
    write(tmp_path, "specs/models.md", MODELS)
    write(tmp_path, "specs/bindings.toml", "")
    project = load_project(tmp_path)
    assert dag_svg(project, check_project(project)) == ""
    page, _ = render(project)
    assert '<svg class="dag"' not in page


def test_dag_skipped_spec_greyed_with_dormant_edges(root: Path) -> None:
    beta = (root / "specs/compute-beta.md").read_text()
    write(root, "specs/compute-beta.md", beta.replace("tier: quick", "tier: quick\nskip: true"))
    project, problems = load_project_lenient(root)
    svg = _svg(render(project, problems)[0])
    # the skipped node stays in the picture, greyed, its dormant edge drawn;
    # report-beta's edge onto the skipped entry was dropped at load
    assert 'class="dag-node skipped"' in svg
    assert svg.count('class="edge"') == 1
    assert 'data-spec="report-beta"' in svg
    assert "<title>fit-beta: skipped</title>" in svg


_SKIPPED_CYCLE = """\
---
name: compute-{me}
kind: compute
tier: quick
skip: true
consumes:
  - fit-{other}
---

# {me}

## Entry

### fit-{me}

Half-written.

Output: `results/{me}/out.json`
"""


def test_dag_survives_dormant_cycle(root: Path) -> None:
    # two skipped specs consuming each other: live edges are cycle-checked,
    # dormant ones are not — the picture must drop them, not crash
    write(root, "specs/compute-x.md", _SKIPPED_CYCLE.format(me="x", other="y"))
    write(root, "specs/compute-y.md", _SKIPPED_CYCLE.format(me="y", other="x"))
    project, problems = load_project_lenient(root)
    svg = _svg(render(project, problems)[0])
    assert svg.count('class="edge"') == 2  # just the live alpha -> beta -> report chain
    assert 'data-spec="compute-x"' in svg and 'data-spec="compute-y"' in svg


_DIAMOND_SPEC = """\
---
name: compute-{me}
kind: compute
tier: quick
{consumes}---

# {me}

## Entry

### fit-{me}

Body.

Output: `results/{me}/out.json`
"""


def test_dag_cli_prints_standalone_svg(root: Path) -> None:
    make_ready(root)
    result = CliRunner().invoke(main, ["dag", "--path", str(root)])
    assert result.exit_code == 0, result.output
    assert result.output.startswith('<?xml version="1.0"')
    assert 'xmlns="http://www.w3.org/2000/svg"' in result.output
    assert "<style>" in result.output  # self-contained: styles inlined,
    assert "var(--" not in result.output  # palette resolved,
    assert "<a " not in result.output  # and no page anchors
    for spec in ("compute-alpha", "compute-beta", "report-beta"):
        assert f'data-spec="{spec}"' in result.output


def test_dag_cli_writes_out_file(root: Path) -> None:
    out = root / "dag.svg"
    result = CliRunner().invoke(main, ["dag", "--path", str(root), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert out.read_text().startswith('<?xml version="1.0"')


def test_dag_json_matches_the_svg_picture(root: Path) -> None:
    make_ready(root)
    project = load_project(root)
    data = dag_json(project, check_project(project))
    assert data is not None
    by = {n["spec"]: n for n in data["nodes"]}
    assert {(e["upstream"], e["downstream"]) for e in data["edges"]} == {
        ("compute-alpha", "compute-beta"),
        ("compute-beta", "report-beta"),
    }
    assert by["compute-alpha"]["layer"] < by["compute-beta"]["layer"]
    assert by["compute-beta"]["entries"] == [{"name": "fit-beta", "status": "ready"}]
    assert by["report-beta"]["kind"] == "report"
    # same layout pass as the SVG: geometry and canvas agree exactly
    svg = _svg(render(project)[0])
    for spec, x in _node_x(svg).items():
        assert by[spec]["x"] == x
    assert f'viewBox="0 0 {data["size"]["width"]} {data["size"]["height"]}"' in svg


def test_dag_cli_json_format(root: Path) -> None:
    result = CliRunner().invoke(main, ["dag", "--path", str(root), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert {n["spec"] for n in data["nodes"]} == {
        "compute-alpha",
        "compute-beta",
        "report-beta",
    }
    # nothing vouched in the raw fixture: statuses ride along
    assert {e["status"] for n in data["nodes"] for e in n["entries"]} == {"audit needed"}


def test_dag_cli_refuses_when_no_flow(tmp_path: Path) -> None:
    write(tmp_path, "specs/models.md", MODELS)
    write(tmp_path, "specs/bindings.toml", "")
    result = CliRunner().invoke(main, ["dag", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "nothing to draw" in result.output


def test_dag_diamond_shares_a_column(tmp_path: Path) -> None:
    consumes = "consumes:\n  - fit-{0}\n"
    write(tmp_path, "specs/compute-a.md", _DIAMOND_SPEC.format(me="a", consumes=""))
    write(tmp_path, "specs/compute-b.md", _DIAMOND_SPEC.format(me="b", consumes=consumes.format("a")))
    write(tmp_path, "specs/compute-c.md", _DIAMOND_SPEC.format(me="c", consumes=consumes.format("a")))
    write(
        tmp_path,
        "specs/compute-d.md",
        _DIAMOND_SPEC.format(me="d", consumes="consumes:\n  - fit-b\n  - fit-c\n"),
    )
    write(tmp_path, "specs/bindings.toml", "")
    svg = _svg(render(load_project(tmp_path))[0])
    x = _node_x(svg)
    assert x["compute-a"] < x["compute-b"] == x["compute-c"] < x["compute-d"]
    assert svg.count('class="edge"') == 4
