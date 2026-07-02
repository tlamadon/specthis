---
name: remote-bytes
kind: library
---

# Remote bytes: record the ledger without holding the outputs

## Motivation

An intensive entry runs on a remote executor (HPC via scripthut, a
colleague's workstation) and its outputs — hundreds of MB — stay
there. Today the machine that fired the run cannot write the
`runs.toml` row (it hashes outputs from local disk), `check` reads the
entry stale on every clone (absent bytes are indistinguishable from
edited ones), and `--fetch` has nothing to pull. The escape hatches
are all bad: committing from the compute node, rsyncing bytes home,
or hand-crafting rows.

The model already permits the fix. Signatures compose from *recorded*
upstream claims, never disk; `output_sha` derives from per-file
digests alone; `fetch` verifies bytes against the claim before
anything lands. Byte-locality only leaks into the model at two
points — `run`'s local hash step and `check`'s disk comparison — and
this spec removes the leak by making it a first-class, orthogonal
dimension: **a claim can stand while its bytes live elsewhere.**

Design narrative: `journal/2026-07-02-remote-compute-ledger-chicken-and-egg.md`.

## Principles

- A ledger row is a claim, not an observation. No status may require
  local bytes; status compares claims against whatever bytes are
  present.
- Signature composition never leaves specthis. No executor, workflow
  step, or human recomputes digests by hand.
- The cache is the home of record for non-materialized outputs, not
  an optimization. Bytes flow node → cache once; clones materialize
  lazily via the existing verified `fetch`.
- Trust boundary unchanged: cache write access. A wrong or forged
  manifest must fail closed at adoption or at fetch, never silently
  poison a clone.

## Entries

### remote-status

`check` distinguishes three byte-states for an entry with a valid run
row (signature matches expected inputs):

- **all declared outputs present, digests match** — ready, as today.
- **all present, composed digest differs** — stale, reason "output
  edited on disk" (no longer conflated with absence).
- **any declared output absent** — the claim stands: the entry reads
  ready, visibly marked as non-materialized (bytes elsewhere,
  fetchable), in `check`, `status`, and the dashboard. It is not
  itemized as a local break and `run --stale` does not rebuild it.

Downstream composition is unaffected (it already reads the recorded
`output_sha`). Note the accepted blind spot: with some outputs absent,
present ones cannot be individually verified (the row holds only the
composed digest); verification happens at `fetch`, which refuses
mismatched bytes. A signature mismatch remains stale regardless of
byte-state.

### remote-manifest

A certify-where-the-bytes-are primitive, runnable on any machine where
the repo checkout and the output bytes coexist (a scripthut task's
last line, a slurm epilogue, another workstation). For one entry it:

- computes the inputs table, signature, and `output_sha` through the
  same code paths `run` uses — never a reimplementation;
- uploads the outputs tarball to the entry's cache key
  (`cache/<signature>/<entry>.tar.gz`, byte-identical layout to what
  `push` produces and `fetch` expects) plus a small manifest sidecar
  (`cache/<signature>/<entry>.manifest.json`) recording the entry
  name, signature, per-output `{path, sha256, size}`, composed
  `output_sha`, executor label, and timestamp;
- records the derived row in the *local clone's* `runs.toml` (same
  claim `run` would write) so that a downstream entry certified later
  in the same remote workflow composes its signature against the
  fresh upstream digest — the tool never commits it; on a disposable
  compute-node clone it dies with the clone;
- requires no git identity and touches no attested claim.

Failure modes fail closed: missing declared outputs, no cache
configured, or an upload error abort before any partial state is
visible at the final cache key.

### remote-adopt

The laptop-side half: record the row for a remotely-certified entry
without ever holding the bytes. Given an entry, adoption:

- computes the expected signature locally (exactly as `run` does
  before executing);
- pulls the manifest at that signature's cache key; a missing
  manifest is a hard refusal naming the signature — this is the
  integrity check: a drifted working tree (dirty, unpushed, wrong
  branch) computes a different signature and finds nothing, so a row
  can never be recorded against inputs that did not produce it;
- verifies the manifest's recorded signature and entry name match,
  then writes the `runs.toml` row from it (executor from the
  manifest), touching nothing else;
- leaves materialization to the existing verified `fetch`, on demand.

Multi-entry pipelines adopt in dependency order; adopting an upstream
entry updates `runs.toml`, which is exactly what makes the
downstream's expected signature match its manifest.
