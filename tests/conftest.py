"""Fixture: a tiny three-level project (fit-alpha -> fit-beta -> fig-beta)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from specthis import hashing
from specthis.check import code_sha, expected_inputs
from specthis.ledger import Run, Vouch, read_runs, record_run, record_vouch
from specthis.parse import load_project

PY = f'"{sys.executable}"'

COMPUTE_ALPHA = """\
---
name: compute-alpha
kind: compute
tier: quick
references:
  - models.md
---

# alpha fit

## Script

Fit the alpha model per models.md.

## Entry

### fit-alpha

The fit must converge and record its loss.

Output: `results/alpha/fit.json`
"""

COMPUTE_BETA = """\
---
name: compute-beta
kind: compute
tier: quick
consumes:
  - fit-alpha
---

# beta fit

## Entry

### fit-beta

Refits beta on top of the alpha fit.

Output: `results/beta/fit.json`
"""

REPORT_BETA = """\
---
name: report-beta
kind: report
consumes:
  - fit-beta
---

# beta figures

## Entries

### fig-beta

Export outputs:
- `reports/fig_beta.tex`
- `reports/fig_beta.dat`
"""

MODELS = """\
---
name: models
kind: definitions
---

# models

Vocabulary only.
"""

BINDINGS = f"""\
[package]
globs = ["src/pkg/**/*.py"]

[entries.fit-alpha]
scripts = ["scripts/fit_alpha.py"]
run = '{PY} scripts/fit_alpha.py'
workflows = ["hut.fit-alpha.json"]

[entries.fit-beta]
scripts = ["scripts/fit_beta.py"]
run = '{PY} scripts/fit_beta.py'

[entries.fig-beta]
scripts = ["scripts/fig_beta.py"]
run = '{PY} scripts/fig_beta.py'
"""

FIT_ALPHA_PY = """\
import json, pathlib
pathlib.Path("results/alpha").mkdir(parents=True, exist_ok=True)
pathlib.Path("results/alpha/fit.json").write_text(json.dumps({"loss": 1.0}))
"""

FIT_BETA_PY = """\
import json, pathlib
alpha = json.loads(pathlib.Path("results/alpha/fit.json").read_text())
pathlib.Path("results/beta").mkdir(parents=True, exist_ok=True)
pathlib.Path("results/beta/fit.json").write_text(json.dumps({"loss": alpha["loss"] + 1}))
"""

FIG_BETA_PY = """\
import json, pathlib
beta = json.loads(pathlib.Path("results/beta/fit.json").read_text())
pathlib.Path("reports").mkdir(exist_ok=True)
pathlib.Path("reports/fig_beta.tex").write_text("\\\\input{fig_beta.dat}")
pathlib.Path("reports/fig_beta.dat").write_text(str(beta["loss"]))
"""

PAPER_TEX = """\
% stand-in for a paper preamble: preview tests declare it as an input
\\section{The beta fit}
"""


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    write(tmp_path, "specs/compute-alpha.md", COMPUTE_ALPHA)
    write(tmp_path, "specs/compute-beta.md", COMPUTE_BETA)
    write(tmp_path, "specs/report-beta.md", REPORT_BETA)
    write(tmp_path, "specs/models.md", MODELS)
    write(tmp_path, "specs/bindings.toml", BINDINGS)
    write(tmp_path, "scripts/fit_alpha.py", FIT_ALPHA_PY)
    write(tmp_path, "scripts/fit_beta.py", FIT_BETA_PY)
    write(tmp_path, "scripts/fig_beta.py", FIG_BETA_PY)
    write(tmp_path, "src/pkg/helpers.py", "X = 1\n")
    write(tmp_path, "hut.fit-alpha.json", '{"backend": "slurm"}\n')
    write(tmp_path, "reports/paper.tex", PAPER_TEX)
    return tmp_path


def vouch_ok(root: Path, entry: str, attester: str = "critic") -> None:
    project = load_project(root)
    e = project.entries[entry]
    c = code_sha(project, e)
    assert c is not None
    record_vouch(
        project.specs_dir,
        entry,
        Vouch(
            spec_sha=e.spec.spec_sha,
            code_sha=c,
            verdict="ok",
            attester=attester,
            vouched="2026-01-01T00:00:00+00:00",
        ),
    )


def fake_run(root: Path, entry: str, execute: bool = True) -> None:
    """Record a run row as `specthis run` would.

    ``execute=False`` records whatever output is already on disk —
    used to simulate a re-run that produced different bytes (the
    fixture scripts are deterministic, so actually executing them
    would rewrite the identical output).
    """
    import subprocess

    project = load_project(root)
    e = project.entries[entry]
    runs = read_runs(project.specs_dir)
    inputs = expected_inputs(project, e, runs)
    if execute:
        assert e.binding.run is not None
        subprocess.run(e.binding.run, shell=True, cwd=root, check=True)
    out_sha = hashing.output_sha(root, e.outputs)
    assert out_sha is not None
    record_run(
        project.specs_dir,
        entry,
        Run(
            signature=hashing.signature(inputs),
            output=", ".join(e.outputs),
            output_sha=out_sha,
            ran="2026-01-01T00:00:00+00:00",
            executor="local",
            inputs=inputs,
        ),
    )


def make_ready(root: Path) -> None:
    """Vouch + run the whole chain so every entry derives READY."""
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)
        fake_run(root, entry)
