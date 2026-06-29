---
title: README
name: README
kind: meta
depends_on: []
---

# specs/

This directory is your project's source of truth for vocabulary and
code contracts. Every file in here is a **specification**: a
declarative description of either (a) what something is (a model
family, an estimator algorithm, a data extract), or (b) what code
must exist in the repo (per-script input/output contracts, naming,
location).

The agent's role (Claude, a subagent, or a future tool) is to author
code that satisfies the contracts in this directory. The user is the
one who runs that code. The spec is testable by reading the code; it
is not testable by running the code.

## File-naming convention

Files are named after the noun being specified. No prefix scheme:
`models.md`, `estimators.md`, `compute-<job>.md`,
`report-<job>.md`. The contents of the file determine what kind of
specification it carries.

| File | Kind | Specifies |
|---|---|---|
| `AGENTS.md` | meta | What an agent should do when working with this directory: audit, propose next steps, author scripts for `script TBD` entries, refresh memory at session start. Read this first. |
| `<topic>.md` | definitions | Reusable vocabulary other specs reference: model families, estimator algorithms, output schema conventions, cluster/runner conventions. |
| `compute-<name>.md` | compute | A fit / data-extraction / analysis job that produces **a JSON file** (plus optional sidecar arrays in the same `results/<...>/` directory). Carries per-entry `Script:` / `Output:` / `Status:` contracts. Compute specs do **not** describe figures, tables, palettes, or LaTeX-bound layout — that prose belongs in the paired report spec. |
| `report-<name>.md` | report | The exporter half of a workflow: consumes one or more compute specs' JSONs and builds figures (`reports/figures/*.tex` + `.dat`) and tables (`reports/tab_*.tex`). Carries `Export script:` / `Export outputs:` / `Status:` per entry; `host_doc:` and `section_label:` in frontmatter route the artefacts to a section of a top-level `.tex` document. Figure design (palette, axis labels, panel structure) and table layout live in the body. |
| `figure-<name>.md` | figure | A **standalone** figure or table exporter: consumes JSON from one or more compute specs and writes a self-contained `.tex` file (table) or `.tex` + `.dat` pair (pgfplots figure) that compiles on its own — no host doc, no routing. Same per-entry contract shape as `report`, but no `host_doc:` / `section_label:`. Use this when the artefact is intended for one-off inspection or ad-hoc inclusion, not as part of a paper-bound document. |

Each workflow is split across **two** files: `compute-<name>.md` for
the fit, and `report-<name>.md` for the export + routing. They pair
by shared stem (e.g. `compute-foo.md` ↔ `report-foo.md`); the
dashboard hops between paired halves with a `↔` link.

## What a specification looks like

A spec is **an authoring contract on code**. It commits the agent
(or a future tool) to producing a script at a declared path that,
when run, produces a declared output. It does not say anything about
whether the script has been run on this machine or whether its
output currently exists on disk — those are observable facts the
audit reports, not part of the spec.

Every compute / report spec is organised around two complementary
sections:

- **`## Script`** (compute) or the per-entry `Export script:` field
  (report) — describes how the code is laid out: the data loader,
  model factory, fit loop, exporter routines. This is *prose about
  how to author the code*. It can be reorganised freely; it is not
  what the dashboard tracks.
- **`## Entry`** / **`## Entries`** — the contract tuple(s) the
  dashboard tracks. Each entry is one `### entry-name` block with:
  - `Script:` (compute) or `Export script:` (report) — the path the
    agent is contracted to author.
  - `Output:` (compute, a single JSON path) or `Export outputs:`
    (report, one or more `reports/...tex` paths) — the schema /
    file the script must produce.
  - `Status:` — `script TBD` or `script ready`. This is the
    script's status, not the output's.

  Single-entry specs use `## Entry` with one block. Multi-entry
  specs (catalogues / sweeps) use `## Entries` containing several
  `### entry-name` blocks.

On the report side, an entry additionally carries an
**`## Artefact design`** block that pins the layout / palette /
caption of each output file. That layout is part of the contract.

A spec file does **not** carry result numbers. Point estimates,
standard errors, log-likelihoods, plot summaries — all of these live
next to the data: in the result JSONs at the output paths declared
by the spec, or in the paper sections cited by the spec. The spec
stays stable as a contract; the results layer is allowed to be
larger, scrappier, and to evolve independently.

## Frontmatter convention

Every `.md` file in this directory begins with a YAML frontmatter
block declaring its name, kind, and explicit dependencies on other
specs:

```yaml
---
name: <spec-name>          # filename stem, no extension
kind: <kind>               # see below
depends_on:
  - <other-spec>.md        # one entry per direct dependency
  - <another-spec>.md
---
```

Valid `kind:` values:

| kind          | meaning                                                                                  |
|---------------|------------------------------------------------------------------------------------------|
| `meta`        | About specs themselves: index, agent behaviour.                                          |
| `definitions` | Reusable vocabulary other specs reference (models, estimators, conventions, cluster).    |
| `templates`   | Reusable table / figure patterns: palette, layout, reference implementation.             |
| `compute`     | Named entries with a `Script:` / `Output:` / `Status:` contract that produce JSON / data |
| `report`      | Named entries with an `Export script:` / `Export outputs:` contract that produce figures/tables; `host_doc:` + `section_label:` in frontmatter routes the artefacts. |
| `figure`      | Standalone figure/table generator: same `Export script:` / `Export outputs:` / `Status:` contract as `report`, but produces a self-contained `.tex` that does NOT route into a host doc. |

`depends_on:` is a single flat list — no distinction between "I
reference for vocabulary" vs "I depend on the artefacts of". Every
entry must be the literal filename of another spec in this
directory. The audit walks `depends_on:` and flags entries not
mentioned anywhere in the body.

## How to add a new spec file

1. Name the file after the noun being specified.
2. Add the frontmatter block above. Pick the right `kind:` and list
   every other spec the body references in `depends_on:`.
3. Decide whether the body carries vocabulary, code contracts, named
   entries, or a mix; structure it accordingly.
4. Add it to the table above (if you maintain a per-project file
   table).
5. If it introduces a new naming convention, document the convention
   near the top of the file itself, and cross-reference here if
   needed.
