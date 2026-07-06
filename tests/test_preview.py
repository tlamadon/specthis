"""Output previews: [preview] parsing, cache keying, rendering, serving."""

import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from specthis.export import render
from specthis.parse import Project, PreviewRecipe, load_project, load_project_lenient
from specthis.preview import Preview, find_recipe, preview_key, render_preview
from specthis.serve import Dashboard, _make_handler

from .conftest import BINDINGS, make_ready, write

PREVIEW_TEX = """
[preview.".tex"]
command = 'cp {input} {out}'
format  = "txt"
inputs  = ["reports/paper.tex"]
"""


def _recipe(project: Project, rel: str) -> PreviewRecipe:
    recipe = find_recipe(project, rel)
    assert recipe is not None
    return recipe


def _render(
    project: Project, rel: str, recipe: PreviewRecipe, cache: Path, **kwargs
) -> Preview:
    result = render_preview(project, rel, recipe, cache, **kwargs)
    assert result is not None  # the fixture output is on disk
    return result


def test_parse_preview_recipes(root: Path) -> None:
    write(
        root,
        "specs/bindings.toml",
        BINDINGS
        + """
[preview]
".png" = 'convert {input} {out}'

[preview.".tex"]
command = 'scripts/preview_tex.sh {input} {out}'
format  = "svg"
inputs  = ["paper/preamble.tex"]
""",
    )
    project = load_project(root)
    png = project.previews[".png"]  # string form: command only, pdf default
    assert png.command == "convert {input} {out}"
    assert png.format == "pdf" and png.inputs == []
    tex = project.previews[".tex"]
    assert tex.format == "svg" and tex.inputs == ["paper/preamble.tex"]
    assert find_recipe(project, "reports/fig_beta.tex") is tex
    assert find_recipe(project, "results/alpha/fit.json") is None


def test_preview_stanza_moves_no_digest(root: Path) -> None:
    """The invariant the agent docs lean on: [preview] is dashboard-only
    vocabulary — adding or editing a recipe expires no vouch, stales no
    run, and changes no entry's status."""
    from specthis.check import check_project

    make_ready(root)
    before = {n: r.status for n, r in check_project(load_project(root)).items()}
    write(root, "specs/bindings.toml", BINDINGS + PREVIEW_TEX)
    assert {n: r.status for n, r in check_project(load_project(root)).items()} == before


@pytest.mark.parametrize(
    ("stanza", "needle"),
    [
        ('[preview]\ntex = "x {out}"\n', "must start with a dot"),
        ('[preview]\n".tex" = "no placeholder"\n', "must place its artifact at {out}"),
        ('[preview.".tex"]\ncommand = "x {out}"\nformat = "docx"\n', "is not one of"),
        ('[preview.".tex"]\ncommand = "x {out}"\ninput = ["a"]\n', "unknown key"),
        ('[preview]\n".tex" = 5\n', "command string or a table"),
    ],
)
def test_preview_grammar_problems(root: Path, stanza: str, needle: str) -> None:
    write(root, "specs/bindings.toml", BINDINGS + stanza)
    _, problems = load_project_lenient(root)
    assert any(p.file == "bindings.toml" and needle in p.message for p in problems)


def test_preview_key_moves_with_exactly_its_inputs(root: Path) -> None:
    make_ready(root)
    write(root, "specs/bindings.toml", BINDINGS + PREVIEW_TEX)
    project = load_project(root)
    rel = "reports/fig_beta.tex"
    recipe = _recipe(project, rel)
    key = preview_key(project, rel, recipe)
    assert key == preview_key(project, rel, recipe)  # stable when nothing moved

    write(root, "reports/paper.tex", "% preamble edited\n")  # declared input
    moved_input = preview_key(project, rel, recipe)
    assert moved_input != key

    write(root, rel, "\\emph{new bytes}\n")  # the output itself
    moved_output = preview_key(project, rel, recipe)
    assert moved_output not in (key, moved_input)

    recipe.command += " # tweaked"
    assert preview_key(project, rel, recipe) != moved_output

    (root / rel).unlink()  # bytes absent -> nothing to address
    assert preview_key(project, rel, recipe) is None


def test_render_preview_runs_once_then_caches(root: Path, tmp_path: Path) -> None:
    make_ready(root)
    write(
        root,
        "specs/bindings.toml",
        BINDINGS + '[preview.".tex"]\ncommand = \'echo ran >> marker && cp {input} {out}\'\n'
        'format = "txt"\n',
    )
    project = load_project(root)
    rel = "reports/fig_beta.tex"
    recipe = _recipe(project, rel)
    cache = tmp_path / "pcache"

    first = _render(project, rel, recipe, cache)
    assert first.path is not None and not first.cached
    assert first.path.read_bytes() == (root / rel).read_bytes()
    assert first.path.is_relative_to(cache)  # outside the project tree

    second = _render(project, rel, recipe, cache)
    assert second.cached and second.path == first.path
    assert (root / "marker").read_text() == "ran\n"  # the command ran exactly once

    write(root, rel, "\\emph{new bytes}\n")  # moved output -> new key -> re-render
    third = _render(project, rel, recipe, cache)
    assert not third.cached and third.path != first.path


def test_render_preview_failure_shows_log_and_is_not_cached(
    root: Path, tmp_path: Path
) -> None:
    make_ready(root)
    write(
        root,
        "specs/bindings.toml",
        BINDINGS + '[preview.".tex"]\ncommand = \': {out}; echo boom >&2; exit 3\'\n',
    )
    project = load_project(root)
    rel = "reports/fig_beta.tex"
    recipe = _recipe(project, rel)
    cache = tmp_path / "pcache"

    for _ in range(2):  # failures re-run every time — a fix heals on reload
        result = _render(project, rel, recipe, cache)
        assert result.path is None and not result.cached
        assert "boom" in result.log
    assert not list(cache.glob("*.pdf"))  # nothing cached

    # exit 0 without an artifact is a failure too, not an empty preview
    write(root, "specs/bindings.toml", BINDINGS + '[preview.".tex"]\ncommand = \': {out}\'\n')
    recipe = _recipe(load_project(root), rel)
    result = _render(project, rel, recipe, cache)
    assert result.path is None and "placed nothing" in result.log


def test_render_preview_timeout(root: Path, tmp_path: Path) -> None:
    make_ready(root)
    write(
        root,
        "specs/bindings.toml",
        BINDINGS + '[preview.".tex"]\ncommand = \': {out}; sleep 5\'\n',
    )
    project = load_project(root)
    rel = "reports/fig_beta.tex"
    recipe = _recipe(project, rel)
    result = _render(project, rel, recipe, tmp_path / "pcache", timeout=0.2)
    assert result.path is None and "timed out" in result.log


@contextmanager
def _served(root: Path):
    dash = Dashboard(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(dash))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def get(path: str) -> tuple[int, str, bytes]:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as resp:
            return resp.status, resp.headers["Content-Type"], resp.read()

    try:
        yield get
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_preview_route_end_to_end(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPECTHIS_PREVIEW_CACHE", str(tmp_path / "pcache"))
    make_ready(root)
    write(root, "specs/bindings.toml", BINDINGS + PREVIEW_TEX)
    with _served(root) as get:
        status, ctype, body = get("/preview/reports/fig_beta.tex")
        assert status == 200 and ctype.startswith("text/plain")
        assert body == (root / "reports/fig_beta.tex").read_bytes()

        # declared output, no recipe for the suffix
        with pytest.raises(urllib.error.HTTPError) as exc:
            get("/preview/results/alpha/fit.json")
        assert exc.value.code == 404

        # not a declared output: the ACL applies to previews too
        with pytest.raises(urllib.error.HTTPError) as exc:
            get("/preview/scripts/fit_alpha.py")
        assert exc.value.code == 404


def test_preview_failure_page_served(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPECTHIS_PREVIEW_CACHE", str(tmp_path / "pcache"))
    make_ready(root)
    write(
        root,
        "specs/bindings.toml",
        BINDINGS + '[preview.".tex"]\ncommand = \': {out}; echo boom >&2; exit 3\'\n',
    )
    with _served(root) as get:
        status, ctype, body = get("/preview/reports/fig_beta.tex")
        assert status == 200 and ctype.startswith("text/html")
        assert b"preview recipe failed" in body and b"boom" in body
        assert b'href="/view/reports/fig_beta.tex"' in body  # back to source


def test_view_page_links_preview_only_when_recipe_exists(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPECTHIS_PREVIEW_CACHE", str(tmp_path / "pcache"))
    make_ready(root)
    write(root, "specs/bindings.toml", BINDINGS + PREVIEW_TEX)
    with _served(root) as get:
        _, _, body = get("/view/reports/fig_beta.tex")
        assert b'href="/preview/reports/fig_beta.tex"' in body
        _, _, body = get("/view/results/alpha/fit.json")
        assert b"/preview/" not in body


FIGURE_PNG = """\
---
name: figure-plot
kind: report
---

# a standalone plot

## Entry

### fig-plot

Export outputs:
- `reports/plot.png`
"""

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00binary-ish"


def test_image_outputs_viewable_raw_and_chips_linked(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPECTHIS_PREVIEW_CACHE", str(tmp_path / "pcache"))
    write(root, "specs/figure-plot.md", FIGURE_PNG)
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports/plot.png").write_bytes(PNG_BYTES)

    page, _ = render(load_project(root))
    assert 'href="/view/reports/plot.png"' in page  # binary but browser-native

    with _served(root) as get:
        status, ctype, body = get("/view/reports/plot.png")
        assert status == 200 and ctype == "image/png" and body == PNG_BYTES
