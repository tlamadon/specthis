from pathlib import Path

import pytest

from specthis.parse import SpecError, load_project, parse_spec

from .conftest import COMPUTE_ALPHA, write


def test_project_parses(root: Path) -> None:
    project = load_project(root)
    assert set(project.entries) == {"fit-alpha", "fit-beta", "fig-beta"}
    assert project.package_globs == ["src/pkg/**/*.py"]

    alpha = project.entries["fit-alpha"]
    assert alpha.outputs == ["results/alpha/fit.json"]
    assert alpha.tier == "quick"
    assert alpha.binding.scripts == ["scripts/fit_alpha.py"]
    assert alpha.spec.references == ["models.md"]

    fig = project.entries["fig-beta"]
    assert fig.outputs == ["reports/fig_beta.tex", "reports/fig_beta.dat"]
    assert fig.consumes == ["fit-beta"]


def test_spec_sha_covers_frontmatter(root: Path) -> None:
    before = parse_spec(root / "specs/compute-alpha.md").spec_sha
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("tier: quick", "tier: intensive"))
    after = parse_spec(root / "specs/compute-alpha.md").spec_sha
    assert before != after  # frontmatter edits count as contract edits


def test_retired_group_and_priority_are_inert(root: Path) -> None:
    """The sidebar is a file tree now. A file still carrying the old keys
    must parse, not error — nobody should have to edit a spec to upgrade."""
    write(
        root,
        "specs/compute-alpha.md",
        COMPUTE_ALPHA.replace("tier: quick", "tier: quick\ngroup: estimation\npriority: 5"),
    )
    spec = parse_spec(root / "specs/compute-alpha.md")
    assert not hasattr(spec, "group") and not hasattr(spec, "priority")
    assert spec.name == "compute-alpha"


def test_display_keys_stay_outside_spec_sha(root: Path) -> None:
    # display-only keys: retitling must not invalidate vouches, so they
    # are carved out of spec_sha. `group:`/`priority:` are retired but
    # stay carved out — putting a leftover line back into the digest
    # would expire every vouch on the file that carries it.
    before = parse_spec(root / "specs/compute-alpha.md").spec_sha
    write(
        root,
        "specs/compute-alpha.md",
        COMPUTE_ALPHA.replace(
            "tier: quick",
            "tier: quick\ntitle: The alpha fit\ngroup: estimation\npriority: 5",
        ),
    )
    tagged = parse_spec(root / "specs/compute-alpha.md")
    assert tagged.spec_sha == before
    assert tagged.title == "The alpha fit"  # the title still lands on the spec


def test_default_binding_convention(root: Path) -> None:
    (root / "specs/bindings.toml").unlink()
    project = load_project(root)
    b = project.entries["fit-alpha"].binding
    assert b.scripts == ["scripts/fit-alpha.py"]

    assert project.package_globs == []


def test_compute_tier_defaults_intensive(root: Path) -> None:
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("tier: quick\n", ""))
    project = load_project(root)
    assert project.entries["fit-alpha"].tier == "intensive"
    assert project.entries["fig-beta"].tier == "quick"  # report defaults quick


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda t: t.replace("references:", "depends_on:"), "retired"),
        (lambda t: t.replace("kind: compute", "kind: banana"), "not one of"),
        (lambda t: t.replace("name: compute-alpha", "name: wrong"), "filename stem"),
        (lambda t: t.replace("Output: `results/alpha/fit.json`", ""), "no `Output:` path"),
        (
            lambda t: t.replace(
                "Output: `results/alpha/fit.json`",
                "Output: `a.json` `b.json`",
            ),
            "exactly one output",
        ),
        (lambda t: t.replace("tier: quick", "tier: warm"), "not one of"),
    ],
)
def test_grammar_violations(root: Path, mutation, match: str) -> None:
    write(root, "specs/compute-alpha.md", mutation(COMPUTE_ALPHA))
    with pytest.raises(SpecError, match=match):
        load_project(root)


def test_missing_frontmatter(root: Path) -> None:
    write(root, "specs/compute-alpha.md", "# no frontmatter\n")
    with pytest.raises(SpecError, match="frontmatter"):
        load_project(root)


def test_duplicate_entry_names(root: Path) -> None:
    write(root, "specs/compute-dup.md", COMPUTE_ALPHA.replace("compute-alpha", "compute-dup"))
    with pytest.raises(SpecError, match="duplicate entry"):
        load_project(root)


def test_unknown_consumes_and_references(root: Path) -> None:
    write(root, "specs/compute-beta.md", (root / "specs/compute-beta.md").read_text().replace("fit-alpha", "fit-nowhere"))
    with pytest.raises(SpecError, match="unknown entry"):
        load_project(root)
    write(root, "specs/compute-beta.md", (root / "specs/compute-beta.md").read_text().replace("fit-nowhere", "fit-alpha"))
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("models.md", "ghosts.md"))
    with pytest.raises(SpecError, match="unknown spec"):
        load_project(root)


def test_export_outputs_inline_form(root: Path) -> None:
    text = (root / "specs/report-beta.md").read_text()
    text = text.replace(
        "Export outputs:\n- `reports/fig_beta.tex`\n- `reports/fig_beta.dat`",
        "Export outputs: `reports/fig_beta.tex` and `reports/fig_beta.dat`",
    )
    write(root, "specs/report-beta.md", text)
    project = load_project(root)
    assert project.entries["fig-beta"].outputs == [
        "reports/fig_beta.tex",
        "reports/fig_beta.dat",
    ]


# ------------------------------------------------------- contract_sha

TWO_ENTRIES = """\
---
name: pair
kind: compute
---

# pair

## Script

Shared contract prose.

## Entries

### fit-one

First contract text.

Output: `results/one.json`

### fit-two

Second contract text.

Output: `results/two.json`
"""


def _pair(root: Path, text: str):
    write(root, "specs/pair.md", text)
    return parse_spec(root / "specs/pair.md")


def test_shared_prose_moves_every_entrys_contract(tmp_path: Path) -> None:
    before = _pair(tmp_path, TWO_ENTRIES)
    after = _pair(tmp_path, TWO_ENTRIES.replace("Shared contract prose.", "Rewritten."))
    for i in (0, 1):
        assert before.entries[i].block_sha == after.entries[i].block_sha
        assert before.entries[i].contract_sha != after.entries[i].contract_sha


def test_block_edit_moves_only_its_own_contract(tmp_path: Path) -> None:
    before = _pair(tmp_path, TWO_ENTRIES)
    after = _pair(tmp_path, TWO_ENTRIES.replace("First contract text.", "Sharpened."))
    assert before.entries[0].contract_sha != after.entries[0].contract_sha
    assert before.entries[1].contract_sha == after.entries[1].contract_sha


def test_semantic_frontmatter_is_shared_contract(tmp_path: Path) -> None:
    before = _pair(tmp_path, TWO_ENTRIES)
    after = _pair(tmp_path, TWO_ENTRIES.replace("kind: compute", "kind: compute\nprops: [x]"))
    assert before.entries[0].contract_sha != after.entries[0].contract_sha


def test_display_and_dormancy_frontmatter_are_not(tmp_path: Path) -> None:
    before = _pair(tmp_path, TWO_ENTRIES)
    retitled = _pair(tmp_path, TWO_ENTRIES.replace("kind: compute", "kind: compute\ntitle: T"))
    skipped = _pair(tmp_path, TWO_ENTRIES.replace("kind: compute", "kind: compute\nskip: true"))
    assert before.entries[0].contract_sha == retitled.entries[0].contract_sha
    assert before.entries[0].contract_sha == skipped.entries[0].contract_sha


def test_trailing_prose_after_last_entry_is_that_entrys_block(tmp_path: Path) -> None:
    # the \Z quirk: with no closing ## heading, trailing prose lives
    # inside the last block — the complement must not double-count it
    text = TWO_ENTRIES + "\nTrailing note.\n"
    before = _pair(tmp_path, text)
    after = _pair(tmp_path, text.replace("Trailing note.", "Different note."))
    assert before.entries[0].contract_sha == after.entries[0].contract_sha
    assert before.entries[1].contract_sha != after.entries[1].contract_sha
