---
title: AGENTS (agent workflows)
name: AGENTS
kind: meta
depends_on:
  - README.md
---

# AGENTS.md — working with specs/

This file is for any agent (Claude, a subagent, a future tool, or
the human user doing the same checks) that needs to work with the
specifications in this directory. It describes the operations the
agent is expected to perform, how to perform them, and the
boundaries.

Read this file before doing anything in `specs/`. If the user asks
you to "check the specs", "audit", or "propose next steps", the
relevant operation below is what they mean.

## What the agent should do

The agent's job is **read specs/, observe the working tree, report
state, propose changes**. The agent does not run the project's
fitting scripts, does not edit result files, and does not modify
the spec files unless explicitly asked.

## Script and entry: the spec's two-section anatomy

Every compute / report spec carries the same two-section structure:

- **`## Script`** (compute) / per-entry `Export script:` field
  (report) — *prose about how to author the code*. It can be
  reorganised freely; it is not what the audit tracks.
- **`## Entry`** (single-entry specs) or **`## Entries`**
  (multi-entry specs) — the contract tuple(s) the audit walks:
  - `Script:` / `Export script:` — the path the agent is contracted
    to author.
  - `Output:` (compute, a JSON path under `results/<...>/`) or
    `Export outputs:` (report, one or more files under `reports/`).
  - `Status:` — `script TBD` or `script ready`.

Each entry is therefore the binding tuple

```
(script path, what the script must do, output path + schema, status)
```

On the report side, an entry is followed by an
**`## Artefact design`** section that pins the layout / palette /
caption of each output file.

## Compute / report responsibility split

This is the single most important rule that follows from the
taxonomy:

- A **compute** spec describes a job whose output is a JSON file
  (plus optional sidecar arrays under the same `results/<...>/`
  directory). That JSON is **the contract**: the fit's parameters,
  diagnostics, log-likelihoods, posterior samples, anything a
  downstream consumer might want. A compute spec does **not**
  describe figures, tables, or LaTeX-bound artefacts; it does not
  declare anything under `reports/`.
- A **report** spec describes one or more exporter scripts whose
  inputs are the JSON outputs of one or more compute specs and
  whose outputs are LaTeX artefacts under `reports/` (tables,
  `figures/*.tex`, `figures/*.dat`). Layout, captions, palette,
  axis ranges, "what to plot" — all live here.

The boundary is enforced both at audit time and at authoring time
(see operations 1 and 3 below). If figure prose, palette choices, or
table column orderings appear inside a compute spec, that is a spec
bug — flag it and propose moving the prose to the paired report
spec.

## Four named operations

### 1. Audit

Walk every `.md` file in `specs/`. Two kinds of files carry per-entry
contracts: `kind: compute` specs (which carry `Script:` / `Output:`
/ `Status:` per entry) and `kind: report` specs (which carry
`Export script:` / `Export outputs:` / `Status:` per entry plus
`host_doc:` / `section_label:` in frontmatter). Compute and report
specs pair by shared stem (`compute-<stem>.md` ↔ `report-<stem>.md`).

#### Compute side

For each named entry in a `kind: compute` spec:

1. Read the declared `Status:` (`script TBD` or `script ready`).
2. Check the `Script:` path on disk:
   - **File exists?** Open it.
   - **Contract holds in spirit?** The script should match the
     contract described in the spec's `## Script` section. Read
     enough of the script to confirm; do not run it.
   - **No report-side work?** The compute script should write to
     `results/<...>/` only. If it writes to `reports/` or emits
     a figure file, flag it as **compute-spec scope creep**: the
     work belongs in the paired report spec's exporter.
3. Check the `Output:` path on disk:
   - **JSON exists?** If yes, open it and confirm the top-level
     keys match the schema declared in the entry contract.
   - **JSON only?** The compute spec's `Output:` field should name
     exactly one JSON path under `results/<section>-<entry>/`. If
     the spec also names a `reports/...tex` path, flag it as
     **routing leak**: that path belongs in the report spec's
     `Export outputs:`.
4. **No figure / table prose**: the compute spec's body must not
   describe figure palettes, axis labels, table column orderings,
   `\input{...}` lines, or any other LaTeX-bound layout. Quickly
   grep for `figure`, `pgfplots`, `tikz`, `\caption`, `\input`,
   `palette`, `axis label`. If present, flag and propose moving to
   the paired report spec.

#### Report side

For each named entry in a `kind: report` spec:

5. Read `Status:` (`script TBD` or `script ready`) and the spec's
   frontmatter `host_doc:` + `section_label:`.
6. **Export script exists?** Open it. Confirm it reads only the
   paired compute entry's `Output:` JSON (or a small set of compute
   JSONs in the aggregator case), writes only to its
   `Export outputs:` paths under `reports/`, and is
   side-effect-free (does not run the fit, does not touch
   `results/`).
7. Each path under `Export outputs:` exists in `reports/`.
   - **Five-state freshness check** — each artefact lands in
     exactly one of these buckets:
     1. **missing** — the file is not on disk.
     2. **stale (contract)** — the owning report entry has
        `Status: script TBD`. Whatever is on disk is from the
        **old** contract.
     3. **stale (mtime)** — `make -dq <path>` returns non-zero and
        at least one non-`specs/` prerequisite (the export script
        or a compute `Output:` JSON) is newer than the artefact.
     4. **needs review** — `make -dq <path>` returns non-zero and
        the **only** newer prerequisite is the report `specs/*.md`
        file itself. The contract **may** have moved but it may
        also be a typo / prose tweak.
     5. **fresh** — file exists, `make -dq` is zero, owning entry
        is `script ready`.
   - `make` exit code `2` ("no rule for target") is **no freshness
     signal**, not a failure.
8. **Routing.** The named `host_doc:` exists under `reports/`.
   Inside it, a `\label{<section_label>}` matching the spec's
   frontmatter exists, and every path in `Export outputs:` has a
   corresponding `\input{...}` / `\includegraphics{...}` line
   inside that labelled section.
9. **Figure / table prose lives here**: every paper-bound artefact
   the report spec declares should also have its layout described
   here — palette, axis labels, panel structure, table column
   ordering, caption intent.
10. **Frontmatter check** (every `.md` file in `specs/`):
    - The file begins with a YAML frontmatter block declaring
      `name`, `kind`, and `depends_on` per the convention in
      `README.md`.
    - `name` matches the filename stem.
    - `kind` is one of the documented enum values (`meta`,
      `definitions`, `templates`, `compute`, `report`, `figure`).
    - Every entry in `depends_on` is the filename of another `.md`
      file in `specs/`, and appears at least once in the body.
    - `kind: report` specs additionally have `host_doc:` and
      `section_label:` set.

Report as two markdown tables, one for compute and one for report:

Compute side:
| entry | spec | status | script ✓ | contract ✓ | output ✓ | schema ✓ | notes |

Report side:
| entry | spec | status | export script ✓ | artefacts ✓ | host_doc | section ✓ | notes |

Keep notes brief. Do **not** run any of the project scripts. Do
**not** open large result JSONs in full — key existence is enough.
Do **not** compile any document under `reports/` — the audit is a
working-tree check, not a build check.

### 2. Propose next steps

After (or as part of) an audit, suggest the next concrete thing the
user could do. A few heuristics:

- If there is an entry with `script TBD` whose model is a small
  variant of a `script ready` entry, that is the natural next
  script to author.
- If every per-entry script is `script ready` but the aggregator is
  `script TBD`, the next step is the aggregator.
- If the aggregator and all per-entry scripts are `script ready`
  but the paper section that includes the aggregator's output does
  not exist in the report spec's `host_doc:`, propose adding that
  section.

Express proposals as "I could now author X" or "the next thing the
user can run is Y" — not as actions the agent has taken. Wait for
explicit confirmation before authoring or running.

### 3. Author a script for a `script TBD` entry

Only when explicitly asked. The procedure differs depending on
whether the `script TBD` lives on the compute or the report side.

**For a compute-spec entry** (`kind: compute`):

1. Re-read the entry's section in the spec and the referenced
   vocab specs (typically `models.md` / `estimators.md`). Treat
   those as the spec.
2. Find the closest existing `script ready` compute entry and copy
   its script as the starting point. Edit only the
   model-construction and post-step hooks. Keep the same JSON
   schema.
3. The script's only output is the entry's `Output:` JSON (plus any
   sidecar arrays in the same `results/<...>/` directory). Do
   **not** emit anything under `reports/`, do **not** import a
   plotting library, do **not** write LaTeX.
4. Smoke-test the script's first few iterations (data loads, model
   builds, first inner step has finite loss). Do **not** run a
   full fit.
5. Flip the entry's `Status:` to `script ready` in the spec.
6. If the project uses the specthis lock manager, run
   `specthis lock record <entry-name>` to certify the inputs.

**For a report-spec entry** (`kind: report`):

1. Re-read the entry's section in the report spec, the paired
   compute spec's `Output:` schema, and any applicable `templates`
   spec for figure conventions.
2. Find the closest existing `script ready` exporter and copy it as
   the starting point. The exporter reads the compute JSON, writes
   one or more files under `reports/`, and does nothing else.
3. Run the exporter end-to-end (it is cheap; not a "fit") and
   confirm the artefacts under `Export outputs:` materialise.
4. Confirm the host document `\input`s or `\includegraphics`s each
   artefact inside the labelled section named by the spec's
   `host_doc:` + `section_label:` frontmatter. Add the lines if
   they are missing.
5. Flip the entry's `Status:` to `script ready` in the report spec.

### 4. Refresh memory at the start of a session

When the user opens a new session and says something like "let's
work on <topic>", do this before anything else:

1. Read `specs/README.md`.
2. Read `specs/AGENTS.md` (this file).
3. Read the relevant paired spec(s) — typically
   `specs/compute-<topic>.md` + `specs/report-<topic>.md` plus any
   referenced vocab specs.
4. Then ask the user what they want to do, or perform the audit if
   they implicitly asked for it.

This gives the agent a clean, durable starting context that does
not depend on prior chat history.

## Status interpretation

The vocabulary for `Status:` lines in a spec file is intentionally
narrow:

- `script TBD` — the spec describes a script that does not yet
  exist on disk, or exists but does not satisfy the contract.
- `script ready` — the spec's script exists, satisfies the
  contract, and has been spot-checked (data loads, model builds,
  first inner step has finite loss). The spec makes no claim
  about whether the script has been *run* on this machine.

Whether the result JSON exists, whether a fit was run, whether the
paper section is up to date — none of these are tracked by
`Status:`. They are observable facts about the working tree and
are reported by the audit operation, not by the spec.

### Status flip on contract changes

A spec edit that changes what the script must do (different output
schema, different figure layout, different table columns, different
palette) breaks the contract for the existing code. The mtime-based
Makefile check **cannot** see this drift — neither the script nor
the artefact moved on disk. The agent **must** therefore flip the
`Status:` to `script TBD` on every affected entry in the same edit
that changes the contract. The `Status:` text should briefly explain
what the script needs to do to satisfy the new contract; once the
script is updated and spot-checked, `Status:` flips back to
`script ready`.

This is the single convention that ties spec edits to the audit
signal. Forget it and the dashboard silently lies about drift.

## What NOT to do

- Do **not** run the project's fitting scripts, the aggregator, or
  any other code that mutates the result layer or burns compute.
  Authoring includes a smoke-test (a handful of iterations);
  running does not.
- Do **not** edit a result JSON or a paper artefact under
  `reports/`. The spec describes what should produce them; only
  the user runs the producer.
- Do **not** describe figures, tables, palettes, or any
  LaTeX-bound layout inside a `kind: compute` spec.
- Do **not** paste result numbers (point estimates, SEs,
  log-likelihoods) into any spec file. Those live in the result
  JSON pointed to by the entry's `Output:` path.
- Do **not** invent new conventions. If something is ambiguous,
  propose an addition to the relevant `definitions` spec and let
  the user decide.
- Do **not** mark an entry as `script ready` unless the spot-check
  passed.
