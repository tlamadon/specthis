import json
import threading
import time
import urllib.request
from pathlib import Path

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
    assert {p.name for p in written} == {"specs.html", "_index.json", "_routing.json"}

    page = (root / "specs/specs.html").read_text()
    for needle in ("fit-alpha", "fit-beta", "fig-beta", "compute-alpha", "ready"):
        assert needle in page
    assert "Frontier" not in page  # everything is ready

    index = json.loads((root / "specs/_index.json").read_text())
    by_name = {s["name"]: s for s in index["specs"]}
    entry = by_name["compute-alpha"]["entries"][0]
    assert entry["name"] == "fit-alpha"
    assert entry["status"] == "ready"
    assert entry["vouch"]["attester"] == "critic"
    assert entry["run"]["executor"] == "local"


def test_export_shows_frontier_and_escapes_html(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# <script>alert(1)</script>\n")
    from .conftest import vouch_ok

    vouch_ok(root, "fit-alpha", attester='critic <b>"x"</b>')
    project = load_project(root)
    page, _, _ = render(project)
    assert "Frontier" in page  # fit-alpha is now stale (re-vouched, not re-run)
    assert "&lt;b&gt;" in page and '<b>"x"</b>' not in page  # attester name escaped
    assert "upstream-unverified" in page or "stale" in page


def test_spec_markdown_is_rendered_for_browsing(root: Path) -> None:
    project = load_project(root)
    page, _, _ = render(project)
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
    page, _, _ = render(load_project(root))
    for raw in ('href="models.md"', 'href="./models.md"', 'href="specs/models.md"'):
        assert raw not in page  # every sibling-spec form rewritten...
    assert 'href="#spec-models"' in page  # ...to the hash-routed section
    assert 'href="https://example.org/doc.md"' in page  # external untouched
    assert 'href="missing.md"' in page  # unknown stem untouched


def test_sidebar_and_hash_routing(root: Path) -> None:
    project = load_project(root)
    page, _, _ = render(project)
    # one nav entry per spec file, grouped by kind, plus the status shortcut
    assert '<nav class="sidebar">' in page
    assert 'data-file-anchor="status"' in page
    for anchor in ("spec-compute-alpha", "spec-compute-beta", "spec-report-beta", "spec-models"):
        assert f'data-file-anchor="{anchor}"' in page
        assert f'<section class="spec" id="{anchor}">' in page
    assert '<span class="kind kind-definitions">definitions</span>' in page
    # spec titles come from the first heading
    assert ">alpha fit</a>" in page
    # the hash router and scroll-preserving reload ship inline
    assert "anchorToFile" in page
    assert "specsScrollY" in page
    assert "MathJax" in page


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
    assert "audit needed" in dash.html


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
        assert b"audit needed" in body
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        time.sleep(0)
