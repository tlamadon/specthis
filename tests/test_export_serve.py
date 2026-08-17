import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.check import check_project
from specthis.cli import main
from specthis.export import build_index, render, write_artefacts
from specthis.parse import load_project
from specthis.serve import Dashboard, _make_handler

from .conftest import make_ready, write


def test_export_writes_html_and_index(root: Path) -> None:
    make_ready(root)
    written = write_artefacts(root)
    assert {p.name for p in written} == {"specs.html", "_index.json"}

    page = (root / "specs/specs.html").read_text()
    for needle in ("fit-alpha", "fit-beta", "fig-beta", "compute-alpha", "ready"):
        assert needle in page
    assert 'badge stale">' not in page  # everything is ready — no broken badges

    index = json.loads((root / "specs/_index.json").read_text())
    by_name = {s["name"]: s for s in index["specs"]}
    entry = by_name["compute-alpha"]["entries"][0]
    assert entry["name"] == "fit-alpha"
    assert entry["status"] == "ready"
    assert entry["vouch"]["attester"] == "critic"
    assert entry["run"]["executor"] == "local"
    assert entry["certification"] == "certified"
    assert entry["realization"] == "current"
    assert entry["computable"] and entry["realized"]


def test_activity_log_lists_ledger_claims_and_journal_newest_first(root: Path) -> None:
    """#activity is a routable feed: one row per current vouch/run claim
    plus one per journal entry, sorted newest first."""
    make_ready(root)  # all vouches and runs stamped 2026-01-01
    write(root, "journal/2025-12-15-kickoff.md", "# Kickoff\n\nFirst narrative.\n")
    # bump one vouch to a later stamp so ordering is observable
    from specthis.check import code_sha
    from specthis.ledger import Vouch, record_vouch

    project = load_project(root)
    e = project.entries["fit-alpha"]
    c = code_sha(project, e)
    assert c is not None
    record_vouch(
        project.specs_dir,
        "fit-alpha",
        Vouch(
            spec_sha=e.spec.spec_sha,
            code_sha=c,
            verdict="ok",
            attester="critic",
            vouched="2026-02-01T00:00:00+00:00",
        ),
    )
    page, _ = render(load_project(root))

    assert '<section class="spec" id="activity">' in page
    assert '<a href="#activity">Activity log</a>' in page
    body = page.split('id="activity">')[1].split("</section>")[0]
    assert body.count('badge evt-vouch">vouched ok<') == 3
    assert body.count('badge evt-run">ran<') == 3
    assert body.count('badge evt-journal">journal<') == 1
    # newest first: the Feb re-vouch, then the Jan events, the Dec journal last
    rows = body.split("<tbody>")[1].split("<tr>")[1:]
    assert "2026-02-01" in rows[0] and 'evt-vouch">' in rows[0]
    assert "2025-12-15" in rows[-1] and 'evt-journal">' in rows[-1]
    assert 'data-sort="2026-01-01T00:00:00+00:00"' in body  # sortable by raw stamp


def test_vouch_tree_is_landing_and_run_tree_excludes_libraries(root: Path) -> None:
    """The vouch tree is the first section (the router's default page);
    the run page lists only entries with a run axis."""
    make_ready(root)
    page, _ = render(load_project(root))
    first = page.index('<section class="spec" id="vouch">')
    second = page.index('<section class="spec" id="run">')
    assert first < second
    assert '<a href="#vouch">Vouch tree</a>' in page
    assert '<a href="#run">Run tree</a>' in page
    # the DAG (vouch axis) sits on the vouch page, before the run page
    assert first < page.index('<svg class="dag"') < second
    # focus machinery lives on the vouch page; run rows still get detail cards
    assert page.index('id="focus-bar"') < second
    run_body = page.split('id="run">')[1].split("</section>")[0]
    assert '<tr class="detail">' in run_body
    assert "focus-btn" not in run_body


def test_spec_page_vouch_note_is_tooltip_only(root: Path) -> None:
    """The spec-page entries table shows verdict/attester/date; the long
    vouch note lives in a title tooltip, not inline in the cell."""
    from specthis.export import _entry_rows

    from .conftest import vouch_ok

    make_ready(root)
    note = 'All 11 "symbols" present — long rationale prose'
    vouch_ok(root, "fit-alpha", note=note)
    project = load_project(root)
    reports = check_project(project)
    spec = project.entries["fit-alpha"].spec
    rows = _entry_rows(spec, project, reports)
    assert 'title="All 11 &quot;symbols&quot; present — long rationale prose"' in rows
    assert f" — {note}" not in rows  # no inline wall of text
    # the attester and the date are atoms: neither may break mid-token,
    # which is how a squeezed column put a date on three lines
    assert (
        '<span class="who">by <span class="name">critic</span>, '
        '<span class="when">2026-01-01</span></span>'
    ) in rows


def test_export_shows_frontier_and_escapes_html(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# <script>alert(1)</script>\n")
    from .conftest import vouch_ok

    vouch_ok(root, "fit-alpha", attester='critic <b>"x"</b>')
    project = load_project(root)
    page, _ = render(project)
    assert 'badge stale">stale<' in page  # fit-alpha re-vouched, not re-run
    assert "&lt;b&gt;" in page and '<b>"x"</b>' not in page  # attester name escaped


def test_tree_pages_columns_and_sorter(root: Path) -> None:
    make_ready(root)
    (root / "reports/fig_beta.dat").unlink()  # fig-beta -> current, bytes remote
    page, index = render(load_project(root))
    # each tree page carries its own schema
    for th in ("<th>vouch state</th>", "<th>by</th>", "<th>vouched</th>",
               "<th>moved since vouch</th>"):
        assert th in page
    for th in ("<th>run state</th>", "<th>ran</th>", "<th>via</th>", "<th>cached</th>"):
        assert th in page
    assert page.count("<th>kind/tier</th>") == 2  # on both tree pages
    assert ">compute/quick</td>" in page
    assert '<section class="spec" id="vouch">' in page
    assert '<section class="spec" id="run">' in page
    assert '<table class="sortable">' in page
    assert "table.sortable" in page  # the click-to-sort JS ships inline
    assert ">disk</td>" in page  # fit-alpha/fit-beta bytes on this disk
    assert ">remote</span>" in page  # fig-beta claim stands, bytes elsewhere
    # stamp cells: sort key is the full ISO stamp, the cell shows the date
    assert 'data-sort="2026-01-01T00:00:00+00:00"' in page
    assert ">2026-01-01</td>" in page
    flat = {e["name"]: e for s in index["specs"] for e in s["entries"]}
    assert flat["fit-alpha"]["materialized"] is True
    assert flat["fig-beta"]["materialized"] is False


def test_status_table_focus_and_detail(root: Path) -> None:
    make_ready(root)
    page, index = render(load_project(root))
    # rows carry the DAG so the client-side focus filter can walk it
    assert 'data-name="fit-beta" data-consumes="fit-alpha"' in page
    assert 'data-name="fig-beta" data-consumes="fit-beta"' in page
    assert "focus-btn" in page and 'id="focus-bar"' in page
    assert "specsFocus" in page  # focus survives the live-reload cycle
    # each row has a collapsed detail card with the entry neighborhood
    assert '<tr class="detail">' in page
    assert '<span class="lbl">consumed by</span>' in page
    flat = {e["name"]: e for s in index["specs"] for e in s["entries"]}
    assert flat["fit-alpha"]["consumed_by"] == ["fit-beta"]
    assert flat["fig-beta"]["consumes"] == ["fit-beta"]
    assert flat["fig-beta"]["consumed_by"] == []


def test_detail_card_diagnoses_broken_entries(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_beta.py").write_text("# edited\n")  # fit-beta -> both queues
    page, _ = render(load_project(root))
    assert (
        '<span class="lbl">why</span> mind: spec or code moved since vouch; '
        "machine: moved: ~scripts/fit_beta.py" in page
    )
    assert '<span class="lbl">why</span> waiting on fit-beta' in page  # fig-beta


def test_spec_markdown_is_rendered_for_browsing(root: Path) -> None:
    project = load_project(root)
    page, _ = render(project)
    assert '<div class="md">' in page
    assert "<h2>Script</h2>" in page  # compute-alpha's "## Script" heading
    assert "Fit the alpha model per models.md." in page  # its prose
    assert "<h2>The beta fit</h2>" not in page  # host docs are not specs


def test_markdown_spec_links_are_hash_routed(root: Path) -> None:
    from .conftest import COMPUTE_ALPHA

    text = COMPUTE_ALPHA.replace(
        "Fit the alpha model per models.md.",
        "Per [models](models.md), [also](./models.md), [again](specs/models.md); "
        "see [ext](https://example.org/doc.md) and [gone](missing.md).",
    )
    write(root, "specs/compute-alpha.md", text)
    page, _ = render(load_project(root))
    for raw in ('href="models.md"', 'href="./models.md"', 'href="specs/models.md"'):
        assert raw not in page  # every sibling-spec form rewritten...
    assert 'href="#spec-models"' in page  # ...to the hash-routed section
    assert 'href="https://example.org/doc.md"' in page  # external untouched
    assert 'href="missing.md"' in page  # unknown stem untouched


def test_sidebar_and_hash_routing(root: Path) -> None:
    project = load_project(root)
    page, _ = render(project)
    # one nav entry per spec file, plus the tree pages
    assert '<nav class="sidebar">' in page
    assert 'data-file-anchor="vouch"' in page
    assert 'data-file-anchor="run"' in page
    for anchor in ("spec-compute-alpha", "spec-compute-beta", "spec-report-beta", "spec-models"):
        assert f'data-file-anchor="{anchor}"' in page
        assert f'<section class="spec" id="{anchor}">' in page
    assert '<span class="kind kind-definitions">definitions</span>' in page
    # the sidebar says the file name; the title heads the section
    assert ">compute-alpha.md</a>" in page
    assert "alpha fit" in page
    # the hash router and scroll-preserving reload ship inline
    assert "anchorToFile" in page
    assert "specsScrollY" in page
    assert "MathJax" in page


# ------------------------------------------------------- the file tree


NOTE = """\
---
name: {name}
kind: definitions
---

# {name}

Vocabulary only.
"""


def with_files(root: Path, *names: str) -> Path:
    """Add dot-named definition specs — the tree's raw material."""
    for name in names:
        write(root, f"specs/{name}.md", NOTE.format(name=name))
    return root


def sidebar_of(root: Path) -> str:
    """The <nav> only — the stylesheet above it names every pill class."""
    page, _ = render(load_project(root))
    return page[page.index('<nav class="sidebar">') : page.index("</nav>")]


def test_dots_in_a_file_name_are_folders(root: Path) -> None:
    """The VS Code move: `compute.omega.weights.md` lives at
    compute > omega > weights.md, and nothing declared it."""
    sidebar = sidebar_of(with_files(root, "compute.omega.weights", "compute.psi"))
    assert '<details class="nav-dir" open data-dir="compute">' in sidebar
    assert '<details class="nav-dir" open data-dir="compute.omega">' in sidebar
    assert '<span class="dir-name">omega</span>' in sidebar
    # the leaf shows its own segment; the full name is the tooltip
    assert 'title="compute.omega.weights.md">weights.md</a>' in sidebar
    assert 'title="compute.psi.md">psi.md</a>' in sidebar


def test_folders_come_before_files_each_alphabetical(root: Path) -> None:
    sidebar = sidebar_of(with_files(root, "zeta", "alpha.one", "alpha.two"))
    assert sidebar.index('data-dir="alpha"') < sidebar.index(">zeta.md</a>")
    assert sidebar.index(">one.md</a>") < sidebar.index(">two.md</a>")


def test_a_file_that_is_also_a_folder_is_both(root: Path) -> None:
    """`compute.md` beside `compute.omega.md` is an overview next to its
    parts — one row that both links and opens."""
    sidebar = sidebar_of(with_files(root, "compute", "compute.omega"))
    opener = sidebar.index('data-dir="compute"')
    summary = sidebar[opener : sidebar.index("</summary>", opener)]
    assert 'data-file-anchor="spec-compute"' in summary  # it links to its own section
    assert ">compute.md</a>" in summary


def test_rows_carry_counts_and_folders_aggregate_them(root: Path) -> None:
    """Pills: how many entries, and what they are waiting on. A folder
    answers for everything under it."""
    sidebar = sidebar_of(root)
    # compute-alpha declares one entry, unvouched and never run
    assert '<span class="pill pill-num pill-entries" title="1 entries">1</span>' in sidebar
    assert '<span class="pill pill-num pill-mind" title="1 needing a mind">1</span>' in sidebar
    assert '<span class="pill pill-num pill-machine" title="1 needing a machine">1</span>' in sidebar

    make_ready(root)  # vouched and run: the attention pills go quiet
    quiet = sidebar_of(root)
    assert "pill-entries" in quiet
    assert "pill-mind" not in quiet
    assert "pill-machine" not in quiet


def test_a_folder_sums_its_subtree(root: Path) -> None:
    for stem in ("compute-alpha", "compute-beta"):
        old = root / f"specs/{stem}.md"
        # `name:` must match the filename stem, so moving a file into a
        # folder is a rename of both — which is the whole cost of the tree
        write(root, f"specs/grp.{stem}.md", old.read_text().replace(
            f"name: {stem}", f"name: grp.{stem}"
        ))
        old.unlink()
    sidebar = sidebar_of(root)
    summary = sidebar[sidebar.index('data-dir="grp"') :]
    summary = summary[: summary.index("</summary>")]
    assert 'title="2 entries">2</span>' in summary

    # and when the folder is *also* a file, its row answers for the whole
    # subtree — anything you can collapse must say what collapsing hides
    write(root, "specs/grp.md", NOTE.format(name="grp"))
    sidebar = sidebar_of(root)
    summary = sidebar[sidebar.index('data-dir="grp"') :]
    summary = summary[: summary.index("</summary>")]
    assert ">grp.md</a>" in summary
    assert 'title="2 entries">2</span>' in summary


def test_kind_and_tier_pills_ride_every_row(root: Path) -> None:
    write(
        root,
        "specs/compute-beta.md",
        (root / "specs/compute-beta.md").read_text().replace("tier: quick", "tier: intensive"),
    )
    sidebar = sidebar_of(root)
    # with kind headers gone, the row is the only place that says report
    assert '<span class="pill kind-compute" title="compute">' in sidebar
    assert '<span class="pill kind-report" title="report">' in sidebar
    assert '<span class="pill pill-tier" title="intensive">' in sidebar


def test_the_section_stream_follows_the_sidebar(root: Path) -> None:
    page, _ = render(load_project(with_files(root, "zeta", "alpha.one")))
    body = page[page.index("</nav>") :]
    assert body.index('id="spec-alpha.one"') < body.index('id="spec-zeta"')


def test_retired_group_frontmatter_no_longer_organizes_anything(root: Path) -> None:
    """It parses (nobody must edit a spec to upgrade) and does nothing."""
    path = root / "specs/compute-alpha.md"
    path.write_text(path.read_text().replace("name: compute-alpha", "name: compute-alpha\ngroup: estimation\npriority: 5"))
    page, index = render(load_project(root))
    assert "estimation" not in page
    assert "group" not in index["specs"][0]
    assert "priority" not in index["specs"][0]


def test_export_view_is_pure_join(root: Path) -> None:
    # exporting must not change any status or ledger byte
    make_ready(root)
    ledgers = [root / "specs/vouches.toml", root / "specs/runs.toml"]
    before_bytes = [p.read_bytes() for p in ledgers]
    before_status = {n: r.status for n, r in check_project(load_project(root)).items()}
    write_artefacts(root)
    write_artefacts(root)  # and the artefacts it wrote don't feed back in
    assert [p.read_bytes() for p in ledgers] == before_bytes
    assert {n: r.status for n, r in check_project(load_project(root)).items()} == before_status


def test_index_matches_check(root: Path) -> None:
    make_ready(root)
    (root / "reports/fig_beta.dat").unlink()  # fig-beta -> ready, bytes remote
    project = load_project(root)
    reports = check_project(project)
    index = build_index(project, reports)
    flat = {e["name"]: e["status"] for s in index["specs"] for e in s["entries"]}
    assert flat == {n: r.status.value for n, r in reports.items()}


def test_text_output_chips_link_to_viewer(root: Path) -> None:
    make_ready(root)
    (root / "reports/fig_beta.dat").unlink()  # ready, bytes remote
    page, _ = render(load_project(root))
    assert 'href="/view/results/alpha/fit.json"' in page
    assert 'href="/view/reports/fig_beta.tex"' in page
    assert 'href="/view/reports/fig_beta.dat"' not in page  # nothing to open
    assert "<code>reports/fig_beta.dat</code>" in page  # still listed plain
    assert "output-link" in page  # the file:// degradation JS has a target


def test_binary_outputs_are_not_clickable(root: Path) -> None:
    make_ready(root)
    (root / "results/alpha/fit.json").write_bytes(b"\x00\x01PNGish")
    page, _ = render(load_project(root))
    assert 'href="/view/results/alpha/fit.json"' not in page
    assert "<code>results/alpha/fit.json</code>" in page


def test_view_route_serves_declared_text_outputs(root: Path) -> None:
    from http.server import ThreadingHTTPServer

    make_ready(root)
    (root / "reports/fig_beta.dat").unlink()
    dash = Dashboard(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(dash))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        def get(path: str) -> tuple[int, bytes]:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as resp:
                return resp.status, resp.read()

        status, body = get("/view/results/alpha/fit.json")
        assert status == 200
        assert b"&quot;loss&quot;" in body  # file content, escaped, in the page
        assert b"language-json" in body and b"highlight.min.js" in body

        # existing repo files that no entry claims are never served
        for path in ("/view/specs/vouches.toml", "/view/scripts/fit_alpha.py"):
            with pytest.raises(urllib.error.HTTPError) as exc:
                get(path)
            assert exc.value.code == 404

        # declared but bytes-remote -> 404, matching the unlinked chip
        with pytest.raises(urllib.error.HTTPError) as exc:
            get("/view/reports/fig_beta.dat")
        assert exc.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        time.sleep(0)


def test_output_path_never_escapes_the_root(root: Path) -> None:
    dash = Dashboard(root)
    assert dash.output_path("results/alpha/fit.json") is not None
    for rel in ("../etc/passwd", "specs/runs.toml", "/etc/passwd", ""):
        assert dash.output_path(rel) is None


def test_export_cli(root: Path) -> None:
    result = CliRunner().invoke(main, ["export", "--path", str(root)])
    assert result.exit_code == 0, result.output
    assert (root / "specs/specs.html").exists()


def test_dashboard_rerenders_only_on_change(root: Path) -> None:
    make_ready(root)
    dash = Dashboard(root)
    token = dash.token
    assert "fit-alpha" in dash.html
    assert dash.refresh() is False  # nothing moved
    assert dash.token == token

    write(root, "scripts/fit_alpha.py", "# edited\n")
    assert dash.refresh() is True
    assert dash.token == token + 1
    assert "unvouched" in dash.html


def test_dashboard_survives_parse_errors(root: Path) -> None:
    dash = Dashboard(root)
    write(root, "specs/compute-alpha.md", "# no frontmatter\n")
    assert dash.refresh() is True
    assert "does not parse" in dash.html
    from .conftest import COMPUTE_ALPHA

    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA)
    assert dash.refresh() is True
    assert "fit-alpha" in dash.html


def test_server_end_to_end(root: Path) -> None:
    from http.server import ThreadingHTTPServer

    make_ready(root)
    dash = Dashboard(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(dash))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        def get(path: str) -> tuple[int, bytes]:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as resp:
                return resp.status, resp.read()

        status, body = get("/")
        assert status == 200 and b"fit-alpha" in body
        status, body = get("/__state")
        token = json.loads(body)["token"]

        write(root, "scripts/fit_alpha.py", "# edited\n")
        dash.refresh()  # in production the watcher thread does this
        _, body = get("/__state")
        assert json.loads(body)["token"] == token + 1
        _, body = get("/")
        assert b"unvouched" in body
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        time.sleep(0)
