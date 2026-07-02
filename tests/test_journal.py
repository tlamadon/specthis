"""Journal: lenient parsing, the dashboard view, live reload, install."""

from __future__ import annotations

import json
from pathlib import Path

from specthis.export import build_index, render, write_artefacts
from specthis.journal import load_journal
from specthis.parse import load_project
from specthis.serve import Dashboard

from .conftest import write

FIX_ENTRY = """\
# SMC-FFBS resampling fix

The legacy sampler did plain SIS; see [compute-alpha](../specs/compute-alpha.md)
and the earlier [calibration entry](2026-06-10-abb-calibration.md).
Bias did **not** decay as K^-1.
"""

CALIBRATION_ENTRY = """\
---
title: ABB calibration and LoM fits
---

Narrative behind the calibration bundle.
"""


def test_load_journal_dates_titles_and_order(root: Path) -> None:
    write(root, "journal/2026-06-30-smc-ffbs-fix.md", FIX_ENTRY)
    write(root, "journal/2026-06-10-abb-calibration.md", CALIBRATION_ENTRY)
    write(root, "journal/notes.md", "just prose, no heading\n")
    entries = load_journal(root)
    assert [e.stem for e in entries] == [
        "2026-06-30-smc-ffbs-fix",  # newest first
        "2026-06-10-abb-calibration",
        "notes",  # undated sorts last
    ]
    assert entries[0].date == "2026-06-30"
    assert entries[0].title == "SMC-FFBS resampling fix"  # from the # heading
    assert entries[1].title == "ABB calibration and LoM fits"  # frontmatter wins
    assert entries[2].date == ""
    assert entries[2].title == "notes"  # prettified slug fallback


def test_load_journal_without_directory(root: Path) -> None:
    assert load_journal(root) == []


def test_dashboard_renders_journal_view(root: Path) -> None:
    write(root, "journal/2026-06-30-smc-ffbs-fix.md", FIX_ENTRY)
    write(root, "journal/2026-06-10-abb-calibration.md", CALIBRATION_ENTRY)
    page, index, _ = render(load_project(root))
    # sidebar: a journal nav group with the index link and both entries
    assert '<span class="kind kind-journal">journal</span>' in page
    assert 'data-file-anchor="journal"' in page
    assert 'data-file-anchor="journal-2026-06-30-smc-ffbs-fix"' in page
    # index section: filter box + one card per entry, newest first
    assert 'id="journal-filter-input"' in page
    assert page.count('class="journal-card"') == 2
    assert "2 / 2" in page
    assert page.index("smc-ffbs-fix") < page.index("abb-calibration")
    # entry sections carry the date and the rendered narrative
    assert '<section class="spec journal-entry" id="journal-2026-06-30-smc-ffbs-fix">' in page
    assert '<span class="journal-date">2026-06-30</span>' in page
    assert "<strong>not</strong> decay" in page
    # _index.json lists the journal
    assert index["journal"][0] == {
        "file": "journal/2026-06-30-smc-ffbs-fix.md",
        "date": "2026-06-30",
        "title": "SMC-FFBS resampling fix",
    }


def test_journal_links_are_hash_routed_both_ways(root: Path) -> None:
    write(root, "journal/2026-06-30-smc-ffbs-fix.md", FIX_ENTRY)
    write(root, "journal/2026-06-10-abb-calibration.md", CALIBRATION_ENTRY)
    from .conftest import COMPUTE_ALPHA

    text = COMPUTE_ALPHA.replace(
        "Fit the alpha model per models.md.",
        "See the [narrative](journal/2026-06-30-smc-ffbs-fix.md).",
    )
    write(root, "specs/compute-alpha.md", text)
    page, _, _ = render(load_project(root))
    # spec body -> journal section; journal body -> spec + sibling journal
    assert 'href="#journal-2026-06-30-smc-ffbs-fix"' in page
    assert 'href="journal/2026-06-30-smc-ffbs-fix.md"' not in page
    assert 'href="#spec-compute-alpha"' in page
    assert 'href="#journal-2026-06-10-abb-calibration"' in page


def test_journal_titles_are_escaped(root: Path) -> None:
    # Titles land in attribute/nav/card contexts and must escape there;
    # the body itself renders as-is like any spec (the user's own repo
    # content — the same trust level as opening the file in an editor).
    write(root, "journal/2026-06-30-xss.md", '# a <b>"bold"</b> title\n')
    page, _, _ = render(load_project(root))
    assert (
        '<span class="journal-card-title">a &lt;b&gt;&quot;bold&quot;&lt;/b&gt; title</span>'
        in page
    )
    assert '<span class="journal-card-title">a <b>' not in page


def test_export_without_journal_omits_the_view(root: Path) -> None:
    page, index, _ = render(load_project(root))
    assert 'id="journal-filter-input"' not in page
    assert '<span class="kind kind-journal">' not in page
    assert 'class="journal-card"' not in page
    assert index["journal"] == []


def test_export_writes_journal_into_artefacts(root: Path) -> None:
    write(root, "journal/2026-06-30-smc-ffbs-fix.md", FIX_ENTRY)
    write_artefacts(root)
    assert "journal-card" in (root / "specs/specs.html").read_text()
    index = json.loads((root / "specs/_index.json").read_text())
    assert len(index["journal"]) == 1


def test_build_index_defaults_to_empty_journal(root: Path) -> None:
    from specthis.check import check_project

    project = load_project(root)
    assert build_index(project, check_project(project))["journal"] == []


def test_serve_rerenders_on_journal_change(root: Path) -> None:
    dash = Dashboard(root)
    token = dash.token
    write(root, "journal/2026-06-30-smc-ffbs-fix.md", FIX_ENTRY)
    assert dash.refresh() is True
    assert dash.token == token + 1
    assert "SMC-FFBS resampling fix" in dash.html

    # and again when the entry itself is edited
    write(root, "journal/2026-06-30-smc-ffbs-fix.md", FIX_ENTRY + "\nMore.\n")
    assert dash.refresh() is True
    assert dash.refresh() is False  # then quiesces


def test_install_ships_the_journal_command(tmp_path: Path) -> None:
    from specthis.install import install_commands

    install_commands(project_path=tmp_path)
    body = (tmp_path / ".claude" / "commands" / "specthis-journal.md").read_text()
    assert "journal/YYYY-MM-DD-<slug>.md" in body
    assert "touches no ledger" in body
