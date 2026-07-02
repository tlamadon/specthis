# Chicken-and-egg: ledger writes with scripthut-remote compute

## The problem

`specthis run <entry>` assumes the machine that fires the run also ends up
holding the output bytes: it runs the bound command, waits for exit 0, hashes
the declared `Output:` paths from the local filesystem, and only then writes
the `runs.toml` row (`signature`, `output_sha`, `inputs`). Optionally `--push`
uploads the outputs to the shared cache at `cache/<signature>/<entry>.tar.gz`.

When the bound command is `scripthut workflow run …`, that assumption breaks
twice:

1. **The bytes never come home.** scripthut dispatches to the compute node
   (Mercury) and leaves results in the node-side clone
   (`~/scripthut-repos/<sha>/results/…`). The laptop cannot hash a file it
   does not have, so the row is never written, `--push` has nothing to
   archive, and `git pull` on other clones finds no claim to `--fetch`
   against.
2. **The CLI does not even block.** `scripthut workflow run` returns
   immediately after submission; completion is observed via
   `scripthut run watch`. So the "wait for exit 0, then hash" flow in
   `_execute_entry` is already wrong for remote entries, independent of the
   hashing problem. Dispatch and record want to be separate steps.

## What the code says is actually needed

Reading both codebases narrows the gap considerably:

- **The signature never needed the bytes.** `expected_inputs`
  (`src/specthis/check.py`) composes the inputs table from local
  script/package digests plus each upstream's *recorded* `output_sha` — the
  claim, not the bytes — and `run` computes it before the subprocess starts.
- **`output_sha` is derivable from per-file sha256s alone**
  (`src/specthis/hashing.py`): one output → its raw file digest; several →
  `manifest_sha` over sorted `(path, sha)` pairs. No bytes required if
  something trustworthy reports the shas.
- **A wrong claim fails closed.** `fetch` verifies unpacked bytes against the
  recorded `output_sha` before anything lands (`src/specthis/cache.py`), so a
  bad remotely-reported sha cannot silently poison a clone — it makes
  `--fetch` refuse.
- **scripthut has most of the machinery already**: post-completion output
  collection (path + size, no sha yet), cluster-side `sha256sum` for its own
  result cache, and `run view --json` with per-task metadata including
  `commit_hash`. But there is *no* CLI-level env injection at submit time, so
  the laptop cannot pass the precomputed signature through to the task.

So the only missing datum is the per-output sha256, and the only missing
byte-movement is node → cache.

## Escape hatches considered and rejected

- **Commit the row from Mercury** — needs git identity + write access on the
  compute node, pollutes history with automated bumps.
- **rsync/scp the bytes back after every run** — fine at tens of MB, painful
  at hundreds of MB or hours-of-day cadence.
- **Push to S3 from Mercury, skip the row** — `check` reads stale forever;
  `--fetch` refuses because no row exists to verify against.
- **Hand-craft the runs.toml row** — fragile; reimplements signature
  composition and digest semantics by hand.

## Candidate designs

### A. sha-in-job-summary (minimal)

scripthut's output collection already runs `find -printf '%P\t%s\n'`
cluster-side; extend it with `sha256sum` and surface a `sha256` field in
`run view --json`. The laptop then composes `output_sha`, computes the
signature locally as it already does, and records the row — a new
`specthis run <entry> --adopt`-style mode that skips the subprocess and the
local hash.

Sufficient for the **row**, with two caveats:

- **A row without bytes still reads stale everywhere.** `check_project`
  compares disk output digests to the recorded `output_sha`; absent files
  hash to `None`, which never matches. And `--fetch` cannot repair it because
  nothing uploaded a tarball. Fixing this needs a `check` relaxation:
  distinguish *absent* (claim stands, bytes elsewhere — ready, or a new
  `remote`/`fetchable` status) from *edited* (present but different — stale).
  This is arguably more faithful to the ledger philosophy ("a row is a claim,
  not an observation") than the current disk comparison anyway.
- **Integrity check is manual.** Nothing ties the reported sha to the local
  tree; the adopt step must refuse unless local HEAD matches the run's
  `commit_hash` and the tree is clean.

Good enough on its own for entries whose bytes nobody needs locally.

### B. `specthis manifest --push` on the node + `run --adopt` on the laptop (full)

The signature cannot be pushed *into* the task (no env channel), but it does
not need to be: the scripthut clone is the full repo at a pinned commit, so
the node can compute it itself with specthis's own code — signature
composition never leaves specthis.

1. **`specthis manifest <entry> --push`** — appended as the last line of the
   workflow task, on the node that has the bytes. Reuses `expected_inputs` +
   `hashing.output_sha`, pushes the tarball to
   `cache/<signature>/<entry>.tar.gz`, plus a tiny
   `cache/<signature>/<entry>.manifest.json` (output_sha, per-file shas,
   sizes, executor, timestamp). No git identity, no ledger write; the node's
   clone stays disposable. Needs a push-from-computed-values variant of
   `cache.push` (the current one requires an existing row).
2. **`specthis run <entry> --adopt`** — on the laptop after
   `scripthut run watch` completes. Computes the expected signature locally,
   pulls the manifest from the cache at that key, writes the `runs.toml` row.
   Commit and push as usual; every other clone `--fetch`es unchanged.

Keying the manifest by signature doubles as the integrity check for free: a
drifted laptop tree (dirty, unpushed) computes a different signature, finds
no manifest at that key, and fails loudly instead of recording a wrong row.

**Multi-entry remote pipelines**: if B consumes A and both run in one
workflow, `specthis manifest A` must also `record_run` into the *node's own
working-copy* runs.toml (never committed) so B's node-side signature composes
against A's fresh `output_sha`; the laptop then adopts in topo order.

### Non-starter examined: bridging scripthut's result cache

scripthut already content-addresses task outputs into a CAS
(`cas/<content_hash>.tar.gz`) keyed by its action hash. Tempting to
server-side-copy into the specthis cache, but the tarball arcnames are
relative to `$SCRIPTHUT_OUTPUT_DIR`, not the repo root, so `fetch`'s member
lookup would miss — and the two caches answer different questions (task
memoization vs ledger-certified bytes). Keep them separate.

## Where this landed

Design A and B compose rather than compete: A (sha in the job summary +
the `check` absent-vs-edited relaxation) is a small, generic increment and
the `check` change looks worth doing regardless. B is the full contract —
required as soon as any consumer actually needs the bytes, since the upload
from the node is unavoidable then and the node needs the signature to key it.
The deciding question is workload shape: if "hundreds of MB nobody pulls
locally" is the common case, A ships first; entries with real downstream
consumers need B.

## The general shape (added later the same day)

Zooming out, this is a known archetype — Bazel's "builds without the
bytes", git-annex's location tracking — and the right fix is not a
scripthut integration but a model change: **byte-locality becomes a
first-class, orthogonal dimension of an entry's state.** specthis already
separates claims (git), bytes (anywhere), and status (derived); the
implementation conflates them at exactly two points — `run`'s local hash
step and `check`'s disk comparison, where *absent* is indistinguishable
from *edited*. Undo those two conflations and the remote-HPC case falls
out, in four pieces:

1. **`check`: absent ≠ stale.** Valid row + absent bytes reads ready with
   a materialization marker; stale is reserved for present-but-different
   bytes or a moved signature.
2. **`run` splits into dispatch and record.** Every recording path is the
   same funnel — *inputs table + per-output digests → row* — whether the
   digests come from local disk or a manifest. This also absorbs the fact
   that `scripthut workflow run` returns at submission.
3. **One executor-agnostic primitive: certify where the bytes are.**
   `specthis manifest <entry> --push` on any machine holding repo + bytes;
   `specthis run <entry> --adopt` on the machine holding the git pen. The
   signature-keyed manifest makes adoption self-verifying.
4. **Materialization is lazy.** Bytes travel node → cache once; clones
   `fetch` (verified) on demand, possibly never.

Consequences accepted openly: the "cache" becomes the *home of record*
for non-materialized bytes (no eviction on `cache/`; losing the bucket
means recomputing, not losing truth), and the trust boundary stays cache
write access — a forged manifest fails closed at adoption (signature key)
or at fetch (digest check).

This is now specced as a dogfood case — the repo's first `specs/` entry:
`specs/remote-bytes.md`, kind `library`, three entries in order of work
(`remote-status`, `remote-manifest`, `remote-adopt`). `specthis check`
on its own repo duly reports them unimplemented / audit-needed, which is
the tool describing its own missing feature in its own vocabulary.
