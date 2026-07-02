---
name: AGENTS
kind: meta
references:
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

## The one rule that outranks all others

**An agent session that edited an entry's spec or code must never
vouch that entry. Propose the vouch; a separate critic session or the
human holds the pen. Never run `specthis vouch` unless you are that
critic and the human asked.**

The ledger's value is that every attested claim was judged by someone
who did not author the change. An author-stamped vouch is worse than
no vouch: it looks like verification and isn't.

The one sanctioned critic session is the `spec-critic` subagent,
commissioned explicitly by the human (normally via `/specthis-vouch
<name>`). It is freshly spawned, authored nothing, re-derives every
judgment from disk, vouches as `spec-critic (for <name>)` so the
ledger shows the judgment was agent-made, and leaves every doubt
unvouched. No other agent — and no session that edited the code —
ever holds the pen.

## The model in one breath

Each spec entry promises one deliverable. Two ledgers record claims
about it: `specs/vouches.toml` (a named non-author judged that the
code satisfies the contract, at exact digests — written only by
`specthis vouch`) and `specs/runs.toml` (the artefact came from this
code on these exact inputs, as a composed signature over scripts +
package + upstream artefact digests + workflow config — written only
by `specthis run`). `specs/bindings.toml` maps entries to their
scripts and run commands. `specthis check` re-derives everything and
reports, per entry: **unimplemented** / **audit needed** /
**rejected** (a mind's work), **stale** (a machine's work), or
**upstream-unverified** (patience — fix upstream and it heals).
Status is never written anywhere; it is derived. Nothing consults
mtime.

## Spec anatomy: contract + promised output

- **`## Script`** (compute) / export prose (report) — *prose about how
  to author the code*. Part of the contract; names no path.
- **`## Entry`** / **`## Entries`** — the claim unit(s). Each
  `### entry-name` block carries `Output:` (compute, one path under
  `results/`) or `Export outputs:` (report/figure, files under
  `reports/`). No `Script:`, no `Status:` — flag either as **spec
  state leak**.
- Frontmatter: `name`, `kind`, `tier` (compute), `consumes:` (upstream
  entry names — signature-bearing), `references:` (vocabulary spec
  files — ledger-invisible). `depends_on:` is retired; flag it.
- The whole file, frontmatter included, is the contract: any edit
  returns its entries to *audit needed*.

## Compute / report responsibility split

The single most important authoring rule:

- A **compute** spec describes a job whose output is a JSON file
  (plus optional sidecar arrays under the same `results/<...>/`
  directory). That JSON is the contract: parameters, diagnostics,
  log-likelihoods — anything a downstream consumer might want. A
  compute spec does **not** describe figures, tables, or LaTeX-bound
  artefacts and declares nothing under `reports/`.
- A **report** spec describes exporter scripts whose inputs are
  compute entries' JSONs (wired via `consumes:`) and whose outputs are
  LaTeX artefacts under `reports/`. Layout, captions, palette, axis
  ranges — all live here.

If figure prose, palette choices, or table column orderings appear
inside a compute spec, that is a spec bug — flag it and propose moving
the prose to the paired report spec.

## Four named operations

### 1. Audit

Start mechanical, end judgmental:

1. Run `specthis check` (and `specthis status <entry>` for detail —
   it names exactly which input moved). This replaces every
   existence / freshness / hash check you would otherwise do by hand.
   Never re-derive status yourself; never infer it from mtimes.
2. For each entry on the frontier, characterise the repair:
   - **stale** — machine work. Report it; `specthis run --stale` (or
     the user) fixes it. Nothing to judge.
   - **audit needed / rejected** — a mind's work. Open the entry's
     spec section and its scripts (paths are in `specthis status
     <entry>` / `specs/bindings.toml`) and judge **contract in
     spirit**: does the code do what the prose demands? Read enough to
     decide; do not run it.
   - **upstream-unverified** — do nothing locally; point at the
     frontier entry it is waiting on.
3. While reading, also flag: compute-spec scope creep (compute code
   writing under `reports/` or importing plotting libraries), routing
   leaks (a compute `Output:` naming a `reports/` path), spec state
   leaks (`Script:` / `Status:` / `depends_on:` fields), missing
   `## Artefact design` on report entries, and `references:` targets
   never mentioned in the body.
4. Report as a table: entry / status / repair kind (mind, machine,
   patience) / notes. For entries you judged, end each note with a
   **proposed verdict** — "propose vouch ok" or "propose reject:
   <reason>" — for the human or a critic session to act on. Do not
   act on it yourself (see the one rule).

Do not run project scripts, do not open large result files (key
existence is enough), do not compile anything under `reports/`.

### 2. Propose next steps

After (or as part of) an audit:

- **rejected** or **audit needed** entries outrank everything: a
  contract and its code have diverged, and machine repairs downstream
  of them are wasted until a mind rules.
- Then **stale** entries, in dependency order — that is one
  `specthis run --stale` away.
- Then **unimplemented** entries whose contract is a small variant of
  a ready one — the natural next authoring step.

Express proposals as "I could now implement X" or "the next thing to
run is Y" — not as actions taken. Wait for explicit confirmation.

### 3. Implement a spec (author + propose)

Only when explicitly asked:

1. Re-read the entry's spec section and every spec in `references:`.
   Treat those as the contract.
2. Find the closest *ready* entry (`specthis status`) and copy its
   script as the starting point; edit only what the contract demands.
   Keep the declared output schema.
3. Bind the entry in `specs/bindings.toml` (scripts + run command)
   if the default `scripts/<entry>.py` convention doesn't fit.
4. Compute entries: smoke-test only (data loads, model builds, first
   step finite) — never a full fit, never writing the real output.
   Report/figure entries: run the exporter end-to-end (it is cheap)
   and confirm the declared artefacts materialise; confirm the host
   doc routes them (`host_doc:` / `section_label:`).
5. **Stop. Propose the vouch.** Tell the user the entry is ready for
   judgment: "run `specthis vouch <entry> --as <you>`, or hand it to
   a critic session." You authored this change; the pen is not yours.

### 4. Refresh memory at the start of a session

1. Read `specs/README.md`, then this file.
2. Run `specthis check` for the live frontier.
3. Read the spec(s) relevant to the user's topic plus their
   `references:`.
4. Then ask what they want, or audit if they implicitly asked.

## What NOT to do

- Do **not** vouch for anything you (this session) authored or
  edited. Propose; the pen belongs to a non-author.
- Do **not** run fitting scripts or anything that burns compute.
  Authoring includes a smoke-test; running does not.
- Do **not** edit result files or artefacts under `reports/`.
- Do **not** write `Script:`, `Status:`, or `depends_on:` into a
  spec, and do not hand-edit `vouches.toml` or `runs.toml` — ledgers
  are written by their verbs only.
- Do **not** paste result numbers into a spec file.
- Do **not** derive status from mtimes, or from anything other than
  `specthis check` / `specthis status`.
- Do **not** invent new conventions. If something is ambiguous,
  propose an addition to the relevant `definitions` spec and let the
  user decide.
