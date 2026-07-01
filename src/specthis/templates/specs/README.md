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
must exist in the repo (per-entry input/output contracts, output
schema, artefact layout).

A spec describes *what the pipeline should be*. It does **not** record
whether it is implemented yet, where its code lives, whether it has
run, or whether its output exists. Those are facts about the current
state of the repo, tracked in the generated index/lock
(`specs/_index.json` / `specs/_lock.json`) and reported by the audit —
never written into a spec by hand.

The agent's role (Claude, a subagent, or a future tool) is to author
code that satisfies the contracts in this directory, and to register
that code as an **`implements` link** so the certificate can vouch that
spec, code, and output are in sync. The user is the one who runs that
code.

## Nodes and links

specthis treats the pipeline as a **chain of custody**: source data →
transformations → artefacts. It has three kinds of **node** (the actual
things) and links (certified edges) between them:

| Node | What it is |
|---|---|
| **spec** | a hand-written `.md` entry in this directory — the contract. Stable. |
| **code** | a script or module that implements a spec. Path recorded in the lock, never in the spec. |
| **artefact** | an output file (JSON, `.tex`, data). |

| Link | Edge | Certificate |
|---|---|---|
| **implements** | `spec → code` | authorship hash `= hash(spec + code)` — is the code a faithful implementation of the spec? |
| **produces** | `code → artefact` | input signature `= hash(code + upstream artefacts + config)` — did the artefact come from this code on these inputs? |
| **provides** | `spec → artefact` | content hash of the artefact — for source / external data that no code produces |

A spec entry declares the contract and the artefact it promises
(`Output:` — path + schema, the interface downstream links depend on).
It does **not** carry a `Script:` path or a `Status:` field. The code
path is recorded in the `implements` link, written into
`specs/_lock.json` by `specthis lock record` when the code is authored
and spot-checked. A naming convention supplies the default code path;
the binding is explicit, so a spec can be re-implemented elsewhere
without editing the spec.

A chain may **stop at code** (an `implements` link with no `produces`
link) — that is library / shared code that emits no artefact, and it is
valid. A `definitions` spec with no code at all is just a node with no
links: pure vocabulary.

## File-naming convention

Files are named after the noun being specified. No prefix scheme:
`models.md`, `estimators.md`, `compute-<job>.md`,
`report-<job>.md`. The contents of the file determine what kind of
specification it carries.

| File | Kind | Specifies |
|---|---|---|
| `AGENTS.md` | meta | What an agent should do when working with this directory: audit, propose next steps, implement specs, register links, refresh memory at session start. Read this first. |
| `<topic>.md` | definitions | Reusable vocabulary other specs reference: model families, estimator algorithms, output schema conventions, cluster/runner conventions. |
| `compute-<name>.md` | compute | A fit / data-extraction / analysis job that produces **a JSON file** (plus optional sidecar arrays in the same `results/<...>/` directory). Carries a per-entry `Output:` contract (path + schema). Compute specs do **not** describe figures, tables, palettes, or LaTeX-bound layout — that prose belongs in the paired report spec. These are the **intensive** links. |
| `report-<name>.md` | report | The exporter half of a workflow: consumes one or more compute specs' JSONs and builds figures (`reports/figures/*.tex` + `.dat`) and tables (`reports/tab_*.tex`). Carries `Export outputs:` per entry; `host_doc:` and `section_label:` in frontmatter route the artefacts to a section of a top-level `.tex` document. These are **quick** links. |
| `figure-<name>.md` | figure | A **standalone** figure or table exporter: consumes JSON from one or more compute specs and writes a self-contained `.tex` file (table) or `.tex` + `.dat` pair (pgfplots figure) that compiles on its own — no host doc, no routing. Same per-entry `Export outputs:` contract as `report`, but no `host_doc:` / `section_label:`. |

Each workflow is split across **two** files: `compute-<name>.md` for
the fit, and `report-<name>.md` for the export + routing. They pair
by shared stem (e.g. `compute-foo.md` ↔ `report-foo.md`); the
dashboard hops between paired halves with a `↔` link.

## What a specification looks like

A spec is **an authoring contract on code**. It commits the agent
(or a future tool) to producing code that, when run, produces a
declared output. It does not name where that code lives, nor whether
it has been written — those facts are the `implements` link's, not the
spec's.

Every compute / report spec is organised around two complementary
sections:

- **`## Script`** (compute) or the per-entry export prose (report) —
  describes how the code should be laid out: the data loader, model
  factory, fit loop, exporter routines. This is *prose about how to
  author the code*. It is part of the contract (the authorship hash
  covers it), but it does not name a path.
- **`## Entry`** / **`## Entries`** — the contract tuple(s) the
  dashboard and audit track. Each entry is one `### entry-name` block
  with:
  - `Output:` (compute, a single JSON path under
    `results/<section>-<entry>/`) or `Export outputs:` (report, one or
    more `reports/...tex` paths) — the schema / files the code must
    produce. This is the artefact the spec promises: the public
    interface downstream links depend on.

  Single-entry specs use `## Entry` with one block. Multi-entry
  specs (catalogues / sweeps) use `## Entries` containing several
  `### entry-name` blocks.

  Note: an entry carries **no** `Script:` and **no** `Status:`. The
  code path is the `implements` link's, in `specs/_index.json` /
  `specs/_lock.json`.

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
| `compute`     | Named entries with an `Output:` contract that produce JSON / data (intensive links).     |
| `report`      | Named entries with an `Export outputs:` contract that produce figures/tables; `host_doc:` + `section_label:` in frontmatter routes the artefacts (quick links). |
| `figure`      | Standalone figure/table generator: same `Export outputs:` contract as `report`, but produces a self-contained `.tex` that does NOT route into a host doc. |

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
   entries, or a mix; structure it accordingly. For executable kinds,
   give each entry a contract and an `Output:` — but no `Script:` /
   `Status:`.
4. Add it to the table above (if you maintain a per-project file
   table).
5. If it introduces a new naming convention, document the convention
   near the top of the file itself, and cross-reference here if
   needed.

Once the code that satisfies an entry exists and has been
spot-checked, register it with `specthis lock record <entry>` — that
creates the `implements` link and its authorship hash. From then on the
audit can tell you whether spec, code, and output are in sync.
</content>
