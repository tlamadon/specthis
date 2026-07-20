"""The status page's spec-level DAG strip: projection, layout, rendering."""

from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner

from specthis.check import check_project
from specthis.cli import main
from specthis.dag import dag_json, dag_standalone_svg, dag_svg, spec_graph
from specthis.export import render
from specthis.parse import load_project, load_project_lenient

from .conftest import COMPUTE_ALPHA, MODELS, make_ready, write


def _svg(page: str) -> str:
    assert '<svg class="dag"' in page
    return page[page.index('<svg class="dag"'): page.index("</svg>")]


def _node_pos(svg: str) -> dict[str, tuple[int, int]]:
    return {
        m.group(3): (int(m.group(1)), int(m.group(2)))
        for m in re.finditer(
            r'transform="translate\((\d+),(\d+)\)" data-spec="([^"]+)"', svg
        )
    }


def test_spec_graph_projects_consumes_to_spec_level(root: Path) -> None:
    nodes, edges = spec_graph(load_project(root))
    # models (definitions) carries no entries — not part of artefact flow
    assert {s.name for s in nodes} == {"compute-alpha", "compute-beta", "report-beta"}
    assert set(edges) == {
        ("compute-alpha", "compute-beta"),
        ("compute-beta", "report-beta"),
    }


def test_dag_page_is_rails_in_story_order(root: Path) -> None:
    make_ready(root)
    page, _ = render(load_project(root))
    svg = _svg(page)
    pos = _node_pos(svg)
    # story order: every spec below its inputs
    assert pos["compute-alpha"][1] < pos["compute-beta"][1] < pos["report-beta"][1]
    # one spine + one branch per upstream (alpha and beta each feed one spec)
    assert svg.count('class="rail"') == 4
    assert 'href="#spec-compute-beta"' in svg  # rows click through to the spec
    assert 'data-up="compute-beta"' in svg  # hover JS traces a row's inputs
    assert "rails-hover" in page  # the spotlight JS/CSS ships with the page


def test_rails_rows_show_ledger_timing(root: Path) -> None:
    make_ready(root)  # fixture rows: ran/vouched 2026-01-01, no durations
    page, _ = render(load_project(root))
    svg = _svg(page)
    assert 'class="meta"' in svg
    assert "ago" in svg
    # the tooltip itemizes timing per entry
    assert "fit-alpha: ran" in svg


def test_dag_json_carries_ledger_timing(root: Path) -> None:
    make_ready(root)
    project = load_project(root)
    data = dag_json(project, check_project(project))
    assert data is not None
    entries = {e["name"]: e for n in data["nodes"] for e in n["entries"]}
    assert entries["fit-alpha"]["ran"].startswith("2026-01-01")
    assert entries["fit-alpha"]["vouched"].startswith("2026-01-01")
    assert entries["fit-alpha"]["run_seconds"] is None  # fixture recorded none


def test_dag_standalone_layered_top_down(root: Path) -> None:
    make_ready(root)
    project = load_project(root)
    svg = _svg(dag_standalone_svg(project, check_project(project)))
    pos = _node_pos(svg)
    assert pos["compute-alpha"][1] < pos["compute-beta"][1] < pos["report-beta"][1]
    assert svg.count('class="edge"') == 2


def test_dag_cli_orient_lr(root: Path) -> None:
    result = CliRunner().invoke(main, ["dag", "--path", str(root), "--orient", "lr"])
    assert result.exit_code == 0, result.output
    pos = _node_pos(result.output)
    assert pos["compute-alpha"][0] < pos["compute-beta"][0] < pos["report-beta"][0]


def test_dag_dots_follow_status(root: Path) -> None:
    # nothing vouched or run yet: the rail origin dots speak the vouch
    # axis (unvouched orange), the entry chips the run axis (never-run
    # grey) — the two trees visible on one drawing.
    svg = _svg(render(load_project(root))[0])
    assert svg.count('fill="#c06a1f"') == 3  # origin dots: unvouched
    assert svg.count('fill="#9a958c"') == 3  # entry chips: never-run
    assert "never-run (1): fit-alpha" in svg  # group tooltip names the entries
    make_ready(root)
    svg = _svg(render(load_project(root))[0])
    assert svg.count('fill="#4d9367"') == 6  # certified origins + current chips


_REPORT_MANY = """\
---
name: report-many
kind: report
consumes:
  - fit-beta
---

# many exports

## Entries

### exp-one

Export outputs:
- `reports/one.dat`

### exp-two

Export outputs:
- `reports/two.dat`

### exp-three

Export outputs:
- `reports/three.dat`
"""


def test_dag_dots_aggregate_per_status(root: Path) -> None:
    write(root, "specs/report-many.md", _REPORT_MANY)
    svg = _svg(render(load_project(root))[0])
    m = re.search(
        r'<g class="dag-node[^"]*"[^>]*data-spec="report-many"[^>]*>.*?</g></a>', svg, re.S
    )
    assert m is not None
    node = m.group(0)
    # three same-state entries collapse to one chip dot carrying the
    # count (plus the row's vouch-axis dot on the rail)
    assert node.count("<circle") == 2
    assert ">3</text>" in node
    assert "never-run (3): exp-one, exp-two, exp-three" in node


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
    assert svg.count('class="rail"') == 2  # one dormant edge: spine + branch
    assert 'data-spec="report-beta"' in svg
    assert "skipped (1): fit-beta" in svg


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
    # just the live alpha -> beta -> report chain: two upstreams' rails
    assert svg.count('class="rail"') == 4
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
    reports = check_project(project)
    data = dag_json(project, reports)
    assert data is not None
    by = {n["spec"]: n for n in data["nodes"]}
    assert {(e["upstream"], e["downstream"]) for e in data["edges"]} == {
        ("compute-alpha", "compute-beta"),
        ("compute-beta", "report-beta"),
    }
    assert by["compute-alpha"]["layer"] < by["compute-beta"]["layer"]
    assert by["compute-beta"]["entries"] == [
        {
            "name": "fit-beta",
            "status": "ready",
            "certification": "certified",
            "realization": "current",
            "ran": "2026-01-01T00:00:00+00:00",
            "run_seconds": None,
            "vouched": "2026-01-01T00:00:00+00:00",
            "vouch_seconds": None,
        }
    ]
    assert by["report-beta"]["kind"] == "report"
    assert data["orient"] == "tb"
    # the rails placement rides along: story order respects every edge
    for e in data["edges"]:
        assert by[e["upstream"]]["order"] < by[e["downstream"]]["order"]
    assert all(n["lane"] >= 0 for n in data["nodes"])
    # same layout pass as the layered SVG: geometry and canvas agree exactly
    svg = _svg(dag_standalone_svg(project, reports))
    for spec, (x, y) in _node_pos(svg).items():
        assert (by[spec]["x"], by[spec]["y"]) == (x, y)
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


def test_dag_cli_clean_error_without_specs_dir(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["dag", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "no specs/ directory" in result.output  # a clean message, not a traceback


def test_dag_cli_view_rails(root: Path) -> None:
    result = CliRunner().invoke(main, ["dag", "--path", str(root), "--view", "rails"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith('<?xml version="1.0"')
    assert 'class="rail"' in result.output
    assert ".rail {" in result.output  # standalone: rail styles inlined
    assert "<a " not in result.output


def test_dag_cli_refuses_when_no_flow(tmp_path: Path) -> None:
    write(tmp_path, "specs/models.md", MODELS)
    write(tmp_path, "specs/bindings.toml", "")
    result = CliRunner().invoke(main, ["dag", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "nothing to draw" in result.output


def test_dag_diamond_shares_a_row(tmp_path: Path) -> None:
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
    project = load_project(tmp_path)
    svg = _svg(dag_standalone_svg(project, check_project(project)))
    pos = _node_pos(svg)
    assert pos["compute-a"][1] < pos["compute-b"][1] == pos["compute-c"][1] < pos["compute-d"][1]
    assert pos["compute-b"][0] != pos["compute-c"][0]  # side by side in the row
    assert svg.count('class="edge"') == 4
