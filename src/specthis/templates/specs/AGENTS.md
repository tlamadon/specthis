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

The agent's job is **read specs/, observe the working tree and the
index, report state, propose changes**. The agent does not run the
project's fitting scripts, does not edit result files, and does not
modify the spec files unless explicitly asked.

## The three-node model in one breath

A spec entry is a **spec node**: a contract plus the `Output:` it
promises. Whether a spec is implemented, where its code lives, and
whether its output is fresh are **not** in the spec — they are the
**implementation node** and **artifact node**, recorded in
`specs/_index.json` / `specs/_lock.json`:

- **spec node** — hand-written contract in a `.md` entry. Stable.
- **implementation node** — the binding between a spec and its code
  (script + package deps). Registered at certify time; carries a
  **status** and an **authorship hash** `= hash(spec contract +
  script + package deps)`.
- **artifact node** — the output file; carries an **input signature**
  `= hash(implementation hash + upstream artifact signatures +
  config)`.

The certificate is: every edge has a matching hash. `specthis check`
re-derives them and reports the first broken edge.

## Spec anatomy: contract + promised output

Every compute / report spec carries the same structure:

- **`## Script`** (compute) / export prose (report) — *prose about how
  to author the code*. Part of the contract (the authorship hash
  covers it); it names no path.
- **`## Entry`** (single-entry specs) or **`## Entries`**
  (multi-entry specs) — the contract tuple(s) the audit walks. Each
  `### entry-name` block carries:
  - `Output:` (compute, a JSON path under `results/<...>/`) or
    `Export outputs:` (report, one or more files under `reports/`) —
    the artefact the code must produce (path + schema). This is the
    interface downstream steps depend on.

An entry carries **no** `Script:` and **no** `Status:`. The binding
tuple therefore splits across nodes:

```
spec node:            (what the code must do, output path + schema)
implementation node:  (code path, status, authorship hash)   ← in the index
artifact node:        (output path, input signature)          ← in the index
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

Walk every `.md` file in `specs/`, join it against
`specs/_index.json` (spec node ↔ implementation node ↔ artifact node)
and the working tree. Two kinds of files carry per-entry contracts:
`kind: compute` specs (which carry `Output:` per entry) and
`kind: report` specs (which carry `Export outputs:` per entry plus
`host_doc:` / `section_label:` in frontmatter). Compute and report
specs pair by shared stem (`compute-<stem>.md` ↔ `report-<stem>.md`).

The status of a step is read from its **implementation node** in the
index, never from the spec:

- **unimplemented** — no implementation node is registered for this
  entry.
- **ready** — an implementation node is registered, the code exists,
  and its authorship hash matches the current `(spec contract +
  script + package deps)`.
- **audit needed** — an implementation node is registered but its
  authorship hash has drifted: the spec's contract or the code
  changed since it was certified. The code must be re-checked against
  the contract and re-certified (`specthis lock record`).

#### Compute side

For each named entry in a `kind: compute` spec:

1. Read the implementation node status (unimplemented / ready /
   audit needed) from the index.
2. Check the implementation node's code path on disk:
   - **File exists?** Open it only if the status is `audit needed` or
     the index flags a mismatch.
   - **Contract holds in spirit?** The code should match the contract
     described in the spec's `## Script` section. Read enough to
     confirm; do not run it.
   - **No report-side work?** The compute script should write to
     `results/<...>/` only. If it writes to `reports/` or emits a
     figure file, flag it as **compute-spec scope creep**: the work
     belongs in the paired report spec's exporter.
3. Check the `Output:` path on disk:
   - **JSON exists?** If yes, confirm the top-level keys match the
     schema declared in the entry contract.
   - **JSON only?** The compute spec's `Output:` field should name
     exactly one JSON path under `results/<section>-<entry>/`. If the
     spec also names a `reports/...tex` path, flag it as **routing
     leak**: that path belongs in the report spec's `Export outputs:`.
4. **No figure / table prose**: the compute spec's body must not
   describe figure palettes, axis labels, table column orderings,
   `\input{...}` lines, or any other LaTeX-bound layout. Quickly
   grep for `figure`, `pgfplots`, `tikz`, `\caption`, `\input`,
   `palette`, `axis label`. If present, flag and propose moving to
   the paired report spec.

#### Report side

For each named entry in a `kind: report` spec:

5. Read the implementation node status and the spec's frontmatter
   `host_doc:` + `section_label:`.
6. **Export script exists?** Open it (when status warrants). Confirm
   it reads only the paired compute entry's `Output:` JSON (or a small
   set of compute JSONs in the aggregator case), writes only to its
   `Export outputs:` paths under `reports/`, and is side-effect-free
   (does not run the fit, does not touch `results/`).
7. Each path under `Export outputs:` exists in `reports/`.
   - **Five-state freshness check** — each artefact lands in
     exactly one of these buckets:
     1. **missing** — the file is not on disk.
     2. **stale (contract)** — the owning implementation node is
        `unimplemented` or `audit needed`. Whatever is on disk is from
        an old or unverified contract.
     3. **stale (mtime)** — `make -dq <path>` returns non-zero and
        at least one non-`specs/` prerequisite (the export script
        or a compute `Output:` JSON) is newer than the artefact.
     4. **fresh** — file exists, `make -dq` is zero, and the owning
        implementation node is `ready`.
   - The old "needs review" bucket (only the `specs/*.md` is newer, so
     the contract *might* have moved) is gone: the **authorship hash**
     resolves it. If the spec edit changed the contract, the hash
     drifted → the node is already `audit needed` (bucket 2). If the
     edit was a prose tweak, the hash is unchanged → the artefact stays
     `fresh`. No guessing.
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
    - No entry carries a `Script:` or `Status:` field — if one does,
      flag it as **spec state leak**: that belongs in the index.

Report as two markdown tables, one for compute and one for report:

Compute side:
| entry | spec | impl status | code ✓ | authorship ✓ | contract ✓ | output ✓ | schema ✓ | notes |

Report side:
| entry | spec | impl status | export code ✓ | authorship ✓ | artefacts ✓ | host_doc | section ✓ | notes |

Keep notes brief. Do **not** run any of the project scripts. Do
**not** open large result JSONs in full — key existence is enough.
Do **not** compile any document under `reports/` — the audit is a
working-tree check, not a build check.

### 2. Propose next steps

After (or as part of) an audit, suggest the next concrete thing the
user could do. A few heuristics:

- If there is an **unimplemented** entry whose model is a small
  variant of a `ready` entry, that is the natural next step to
  implement.
- If any entry is **audit needed**, that takes priority: the contract
  and code have diverged, so re-check and re-certify before running.
- If every per-entry step is `ready` but the aggregator is
  unimplemented, the next step is the aggregator.
- If the aggregator and all per-entry steps are `ready` but the paper
  section that includes the aggregator's output does not exist in the
  report spec's `host_doc:`, propose adding that section.

Express proposals as "I could now implement X" or "the next thing the
user can run is Y" — not as actions the agent has taken. Wait for
explicit confirmation before authoring or running.

### 3. Implement a spec (author + register)

Only when explicitly asked. The procedure differs depending on
whether the target lives on the compute or the report side.

**For a compute-spec entry** (`kind: compute`):

1. Re-read the entry's section in the spec and the referenced
   vocab specs (typically `models.md` / `estimators.md`). Treat
   those as the spec.
2. Find the closest existing `ready` compute implementation (look it
   up in the index — do not grep the specs for status, which no longer
   carry it) and copy its script as the starting point. Edit only the
   model-construction and post-step hooks. Keep the same JSON schema.
3. The script's only output is the entry's `Output:` JSON (plus any
   sidecar arrays in the same `results/<...>/` directory). Do
   **not** emit anything under `reports/`, do **not** import a
   plotting library, do **not** write LaTeX.
4. Smoke-test the script's first few iterations (data loads, model
   builds, first inner step has finite loss). Do **not** run a
   full fit.
5. **Register the implementation node.** If the smoke-test passes, run

   ```bash
   specthis lock record <entry-name>
   ```

   This writes the spec→code binding, the `ready` status, and the
   authorship hash `hash(spec contract + script + package deps)` into
   `specs/_lock.json` (a tracked file shared with the team). You do
   **not** edit the spec to record status — the status lives on the
   implementation node.

**For a report-spec entry** (`kind: report`):

1. Re-read the entry's section in the report spec, the paired
   compute spec's `Output:` schema, and any applicable `templates`
   spec for figure conventions.
2. Find the closest existing `ready` exporter (via the index) and
   copy it as the starting point. The exporter reads the compute
   JSON, writes one or more files under `reports/`, and does nothing
   else.
3. Run the exporter end-to-end (it is cheap; not a "fit") and
   confirm the artefacts under `Export outputs:` materialise.
4. Confirm the host document `\input`s or `\includegraphics`s each
   artefact inside the labelled section named by the spec's
   `host_doc:` + `section_label:` frontmatter. Add the lines if
   they are missing.
5. Register the implementation node with `specthis lock record
   <entry-name>`.

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

Status is a property of the **implementation node** (in the index),
not of the spec. Its vocabulary is intentionally narrow:

- **unimplemented** — no code is registered for this entry, or none
  exists yet.
- **ready** — the code exists, satisfies the contract, has been
  spot-checked (data loads, model builds, first inner step has finite
  loss), and its authorship hash matches the current spec + code. This
  makes no claim about whether the code has been *run* — that is the
  artifact node's freshness.
- **audit needed** — the authorship hash has drifted from what was
  certified. Something in the contract or the code changed. Re-check
  and re-certify.

Whether the result JSON exists, whether a fit was run, whether the
paper section is up to date — none of these are status. They are the
artifact node's freshness, reported by the audit.

### Contract drift is now automatic

Previously the agent had to remember to hand-flip an entry's status
whenever a spec edit changed the contract, because an mtime check
could not see that the meaning had changed while the files stayed put.
That manual convention is **gone**. A contract edit changes the spec's
content, so the implementation node's authorship hash no longer
matches — the node shows **audit needed** on the next `specthis check`
/ audit, automatically. The agent's remaining job is the honest one:
after changing a contract, re-verify the code still satisfies it, then
re-run `specthis lock record` to re-certify. No status field to
forget.

## What NOT to do

- Do **not** run the project's fitting scripts, the aggregator, or
  any other code that mutates the result layer or burns compute.
  Authoring includes a smoke-test (a handful of iterations);
  running does not.
- Do **not** edit a result JSON or a paper artefact under
  `reports/`. The spec describes what should produce them; only
  the user runs the producer.
- Do **not** write a `Script:` or `Status:` field into a spec. That
  state belongs to the implementation node in the index; register it
  with `specthis lock record`.
- Do **not** describe figures, tables, palettes, or any
  LaTeX-bound layout inside a `kind: compute` spec.
- Do **not** paste result numbers (point estimates, SEs,
  log-likelihoods) into any spec file. Those live in the result
  JSON pointed to by the entry's `Output:` path.
- Do **not** invent new conventions. If something is ambiguous,
  propose an addition to the relevant `definitions` spec and let
  the user decide.
- Do **not** register an implementation node as `ready` unless the
  spot-check passed.
</content>
