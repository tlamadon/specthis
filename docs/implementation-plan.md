# specthis — implementation plan

**Status: 2026-08-11.** How to get from v0.0.32 to the target system in
`specification.md`, in an order that leaves the tool shippable at every
step. §16 of the spec gives the sequence; this gives the work.

---

## Baseline

| | |
|---|---|
| source | 5,535 lines, 16 modules |
| tests | 3,354 lines, **214 passing** |
| largest | `export.py` 1484, `cli.py` 1054, `dag.py` 706, `parse.py` 496 |
| engine | `check.py` 326, `ledger.py` 172, `hashing.py` 95 |

**The engine is small and the surfaces are large.** Every phase below
changes a few dozen lines of `check.py`/`ledger.py` and then pays for it
in `export.py`, `cli.py` and `dag.py`. Budget accordingly: the thinking
is in the engine, the work is in the surfaces.

**Ground rules**

- Green suite at every commit; each phase ends in a release.
- `migrate` absorbs every mechanical rewrite. A user upgrades by running
  one command.
- Legacy rows are read, never rewritten in place by `check` — only
  `migrate` writes.

---

## Phase 1 — pure wins (v0.0.33)

No format change, no delegation. Independently valuable; do these even
if everything after is deferred.

### 1.1 `spec:block` decides certification

`check.py:197` compares file-level `spec_sha`. Compare the entry's
`block_sha` instead — the field is already recorded
(`ledger.py:45 spec_block_sha`) and already used for attribution
(`check.py:167` literally prints *"moved outside this entry's block"*
while expiring anyway).

- Legacy rows with empty `spec_block_sha` fall back to `spec_sha`.
- **Tests:** editing entry B must not expire entry A's vouch in the same
  file; legacy fallback still expires.

*Smallest correctness win available. Removes a whole class of false
expiry.*

### 1.2 Tables authoritative

`_certify` and `_realize` decide on composed digests with the tables
alongside them marked *"diagnostic only"* (`ledger.py:40`). Invert:
compare tables, keep composed digests as a fast path.

- `expired_since_vouch` already produces the attribution — reuse it as
  the decision, not the explanation.
- Add `+path` / `-path` / `~path` to the diff vocabulary.
- **Tests:** added file, removed file, edited file each report distinctly.

### 1.3 Retire the fused status word

Two coordinates, no flattened enum. Vocabulary-only, and the largest
surface in this phase: `Status` flows through `check.py`, `cli.py`,
`export.py`, `dag.py`, `icons.py`.

- Do it **before** anything structural — it is what makes the state
  legible while the rest lands.
- **Tests:** `test_cli`, `test_export_serve`, `test_dag` all assert on
  status strings today; expect churn.

---

## Phase 2 — the ledger reshape (v0.0.34)

One record type, capability-keyed files.

- **`ledger.py`**: replace `Vouch`/`Run` with one `Attestation`
  (`capability`, `pinned`, `verdict`, `actor`, `when`, `evidence`).
  Pseudo-paths `spec:block`, `step:<entry>`, `out:<path>` (§5–§9).
- **Files**: `specs/ledger/*.toml`, **globbed** — never enumerate
  capabilities in code.
- **`out:<path>` per output**, retiring `Run.output`'s comma-joined
  string (`ledger.py:56`), which cannot say *which* output moved.
- **`migrate`** rewrites both old ledgers in place.
- **`remote.py`** adopt path follows.

*No behaviour change a user sees, beyond better multi-output
attribution. Land it alone so the diff is reviewable.*

---

## Phase 3 — the format (v0.1.0 — breaking)

- **`parse.py`**: infer type from fields (§2); drop `kind`/`tier`;
  `produces` takes **logical names**, physical paths only in a source
  entry; per-entry `consumes`.
- **map**: gains `produces = { logical = "path" }`; loses `run`,
  `workflows`, `executor` (they move to the pipeline in Phase 4).
- **`migrate`**: mechanical except one thing — `Output: data/x.parquet`
  needs a *logical name*, which only a human can supply. Prompt per
  output, or accept a mapping file.

*The only phase requiring human input. Version-bump to 0.1.0 and say so
loudly.*

---

## Phase 4 — authored pipeline + lint (v0.2.0)

**These land together or not at all.** An authored pipeline without
complete lint is strictly worse than today: nothing would check that the
graph specthis reports is the graph that runs.

### 4.1 Pipeline reader

New `pipeline.py`. Per backend, parse to
`[{id, command, deps, outs, after}]` (§7.1). Start with **one** backend
so the interface is proven against something real before it is
generalized.

### 4.2 Step digest

`hashing.py`: `step_sha` over command + sorted deps + sorted outs
(§5.6). Enters both pinned tables.

### 4.3 Lint

`lint` already exists (`cli.py:189`) with exactly the right shape —
every problem at once, exit non-zero. Extend it with §13's four groups:
within-spec, spec↔map, spec↔pipeline, map↔pipeline.

The two rules that carry the most weight, because they are what a
generator would have made unrepresentable:

- a `consumes` edge whose upstream `map.produces` value is absent from
  the downstream step's `deps`;
- a `map.scripts` path absent from its step's `deps` — code judged but
  not hashed by the manager, so an edit would expire the vouch without
  staling the run.

**Tests:** `tests/test_lint.py` exists (113 lines) and grows the most of
any test file in this plan.

---

## Phase 5 — the adapter (v0.3.0)

`parse` / `submit` / `poll` / `manifests`, plus optional `probe` (§7.2).

1. **scripthut** — its side is done: `cache_scope: "inputs"`,
   `task probe`, local backend, `manifest_version: 1`. Note the seam
   constraint: no HTTP endpoint runs an inline multi-task document, so
   the plan must be a committed JSON file in a registered source.
2. **Reference runner** (~300 lines) — two backends with no shared
   lineage is what proves the contract is real, and far cheaper than a
   DVC integration.

`run --stale` becomes `submit()` → `poll` → `adopt`. `run --force`
becomes `submit(entries, force=True)`.

---

## Phase 6 — the deletions (v0.4.0)

Only after Phase 5 works end to end:

- `_execute_entry`, `_run_stale_parallel`, dispatch (`cli.py`)
- `cache.py` and the byte-cache half of `remote.py`
- the composed run `signature`
- `[cache] url` from the map

*This is where the line count drops. Do not start it early: the old path
is the fallback until the new one is proven.*

---

## Phase 7 — templates (v0.5.0)

Cheap now (§15). `props` in the spec, `{prop}` in `map.produces`,
instance identity matched **from the output path** — so no backend
naming convention is imposed. Machine ledger keyed per instance; mind
ledger keyed on template *or* instance, the judge choosing by where the
vouch is filed.

---

## Risks

**`export.py` is 1484 lines and touches every phase.** It is the largest
single source of churn and the least covered by anything but
`test_export_serve.py`. Consider a status-vocabulary module that both
`export.py` and `cli.py` render through, introduced in Phase 1.3 while
the change is vocabulary-only.

**Phase 3 breaks every existing project.** cakm is the only real user;
migrate it in the same session and treat whatever creaks as the design
input.

**Phase 4 is the risky one.** It replaces a construction guarantee with
a checking guarantee, and the check must be complete. If lint proves
hard to make exhaustive, that is the signal to reconsider generating the
pipeline after all — the argument against it was churn, not soundness.

---

## Recommended first move

**Phase 1.1 alone**, as a single commit. Ten lines in `check.py`, a
handful of tests, no format change, no migration — and it removes a
false-positive class that fires every time two entries share a file.
It also proves the release loop before anything structural.
