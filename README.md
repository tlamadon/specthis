# specthis

**A notary for a DAG it also knows how to build.** You describe *what
the pipeline should be* in a clean set of specs; specthis keeps one
ledger, versioned in git, of claims about the project — and answers,
cheaply and at any moment: which claims are still true, and what kind
of repair does each broken one need — a mind (re-judge), a machine
(re-run), or patience (upstream will heal it).

> Status: **implemented and tested** — the ledger verbs (`check` /
> `status` / `run` / `vouch` / `migrate`), the scaffolding (`install` /
> `init`), the live dashboard (`export` / `serve`) with spec browsing
> and host-doc routing, and the remote cache. See [Roadmap](#roadmap)
> for the deliberately-deferred extensions.

## The model

**The claim unit is the entry**: one script(-set), one output, one
deliverable. A spec file is a bundle of entries plus the prose
contract they are judged against.

**Two species of claim, verified in opposite directions:**

- **Attested** (spec ↔ code, in `specs/vouches.toml`): someone who did
  *not* author the change judged that the code satisfies the contract,
  at exact digests. Verified backward — are the blobs unchanged since
  the vouch?
- **Derived** (code → artifact, in `specs/runs.toml`): this artifact
  came from this code on these exact inputs, captured as a **composed
  signature** over scripts + package blob + upstream artifact digests
  + workflow config. Verified forward — recompute, compare.

Judgment cannot be computed; computation need not be judged.

**Claims are shallow; trust propagates.** A vouch covers only the
entry's own blobs. When something upstream moves, downstream vouches
don't expire — they get flagged. `specthis check` walks the DAG and
reports the **frontier**: entries broken for local reasons itemized,
everything merely downstream summarized. Per entry the diagnosis is
one of:

| status | meaning | repair |
|---|---|---|
| `unimplemented` | no code on disk | author it |
| `audit needed` | your spec or code moved since the vouch (or was never judged) | a mind |
| `rejected` | a judge said no at exactly these digests | a mind |
| `stale` | inputs moved (or it never ran); the vouch stands | a machine |
| `upstream-unverified` | your claim stands on ground that moved | patience |
| `ready` | every claim checks out | — |

**Two kinds of edge, only one carries trust.** `consumes:` edges are
artifact flows — they enter signatures and propagate status.
`references:` edges are vocabulary — visible to readers and agents,
invisible to the ledger. A definitions hub can be edited without
detonating the certificate graph.

**The pen is guarded.** Attested claims are written only by
`specthis vouch`, which requires a named attester (`--as`, no
git-config default — friction is the feature) and must never be run
by the author of the change, human or agent. A rejection binds at its
exact digest pair: `vouch` refuses an `ok` over a standing rejection
until something changes.

**Executors are ingredients, never authorities.** Intensive entries
dispatch to a configured runner (e.g. scripthut — its cache key is its
own business); quick entries run locally. git holds claims, caches
hold bytes, digests join them. No mtime appears anywhere in ledger
logic: a fresh clone on another machine gives identical answers.

### Division of labor

Three roles, three pens — and only one of them is free-form:

| role | writes | via |
|---|---|---|
| **author** (you, or an implementer agent) | spec edits, code, and the binding in `specs/bindings.toml` (where the code lives, how to run it) | any editor |
| **critic** (a non-author: a colleague, you-next-week, a designated critic session) | attested claims in `specs/vouches.toml` | `specthis vouch --as` — only |
| **machine** | derived claims in `specs/runs.toml` | `specthis run` — only |

The author's pen is unguarded because nothing it writes becomes
trusted on its own: a binding edit changes which files the code
manifest covers, which expires the standing vouch — it can revoke
trust, never mint it. And when the critic vouches, the binding is
swept up in the judgment anyway: the `code_sha` they attest is
computed over exactly the files the binding names, and `run` executes
exactly the command it gives. Author proposes, critic attests,
machine executes — and `check` believes none of them without
re-deriving the digests.

## The five verbs

```bash
specthis check                 # the frontier; exit non-zero on any local break
specthis status [entry]        # table / detail, incl. WHICH input moved
specthis run <entry>           # resolve+record upstream digests -> dispatch -> runs.toml
specthis run --stale           # rebuild every machine-repairable entry in dependency order
specthis vouch <entry> --as NAME [--reject] [--note TEXT]
```

Boundaries are load-bearing: `check`/`status` never write, `run`
never touches `vouches.toml`, `vouch` never touches `runs.toml`.

Two more verbs render **views** — regenerated, never read back by the
ledger:

```bash
specthis export    # write specs/specs.html + _index.json + _routing.json
specthis serve     # live dashboard at localhost:8765; re-renders on any
                   # spec / ledger / code / output / host-doc change (writes nothing)
```

The views include **host-doc routing**: for each report spec declaring
`host_doc:` + `section_label:`, is every exported `.tex` actually
`\input` into that labelled section? Orphaned exports and missing
labels show on the dashboard and as warnings in `check` — warnings
only, never the exit code, because routing is a view concern, not a
claim.

And the **remote cache** moves bytes without ever touching claims:

```bash
specthis cache push <entry>     # upload certified outputs, keyed by signature
specthis cache fetch <entry>    # download + verify against the recorded claim
specthis run --stale --fetch    # try the cache before recomputing
specthis run <entry> --push     # push after a successful run
```

Configure with `[cache] url = "s3://bucket/prefix"` (needs
`specthis[s3]`) or `file:///shared/drive` (no extras) in
`specs/bindings.toml`, or `SPECTHIS_CACHE_URL`. `push` refuses bytes
that don't match the recorded run; `fetch` verifies digests before
anything lands on disk; neither writes a ledger row — git carries the
claim, the cache carries the bytes.

## Use cases

**Change a spec, implement, vouch, run.** The authoring loop. You
tighten the contract in `specs/compute-alpha.md`; every entry in that
file immediately reads *audit needed* — the old vouch bound different
bytes. You (or the `spec-implementer` agent) update the script to
match. Then the two claims are recorded, in order and by different
hands:

```bash
vim specs/compute-alpha.md          # contract edit -> entries flagged: audit needed
vim scripts/fit_alpha.py            # bring the code back in line
specthis vouch fit-alpha --as ana   # a NON-author judges code vs contract
specthis run fit-alpha              # execute, record the derived claim
specthis check                      # ready — and downstream entries now
                                    # show stale, ready for `run --stale`
```

**Did anything change?** The daily question — after a `git pull`,
after an editing session, or when you come back to the project after a
month. One read-only command answers it and names the repair:

```bash
$ specthis check
frontier (broken for local reasons):
  audit needed    fit-beta        spec or code moved since vouch
  stale           fig-gamma       moved: upstream:fit-gamma
waiting on the frontier: 3 upstream-unverified
ready: 11/16
```

Re-judge `fit-beta`, machine-rebuild `fig-gamma`, and the three
downstream entries heal on their own. To see exactly what moved on one
entry — which script, which workflow file, which upstream artifact —
ask `specthis status fit-beta`.

**Rebuild everything a machine can fix.** After an upstream fit
re-ran, or after a migration, every downstream entry with a standing
vouch is just compute:

```bash
specthis run --stale     # topo order; skips audit-needed entries
                         # ("needs a mind, not a machine")
```

**Reject bad work.** A critic reads an implementation and disagrees
with it. The rejection is a claim too — recorded, attributed, and
binding at exactly those digests:

```bash
specthis vouch fit-beta --as ben --reject --note "loss ignores weights"
```

The entry reads *rejected* until the spec or the code actually
changes; `vouch` refuses an `ok` over the standing rejection at the
same pair, so nobody can quietly re-stamp the same bytes.

**Onboard a machine (or a collaborator).** Clone the repo anywhere
and run `specthis check`: same claims, same digests, same answer — no
mtimes to confuse a fresh checkout. Vouches travel with git; artifacts
don't have to. Whatever reads *stale* is one
`specthis run --stale --fetch` away: entries whose recorded claim
matches today's inputs are pulled from the cache (digest-verified,
zero recompute, zero ledger writes); only genuinely new work executes.

**Let agents work, keep the pen.** The `spec-auditor` runs the checks
and judges contract-in-spirit but only ever *proposes* verdicts; the
`spec-implementer` authors code, smoke-tests it, and stops at the
vouch. Sessions end, the ledger remembers: what was judged, by whom,
at which digests — and what still needs a mind, a machine, or
patience.

## State: three human-readable files, all in git

- **`specs/vouches.toml`** — attested claims:
  `(spec_sha, code_sha, verdict, attester, when, note)` per entry.
- **`specs/runs.toml`** — derived claims: the composed signature, the
  output digest, the executor, and the full `[inputs]` table
  (each script, workflow file, the package blob, and one
  `upstream:<entry>` digest per consumed artifact — so an upstream
  re-run is never invisible).
- **`specs/bindings.toml`** — hand-edited vocabulary, not a claim:
  entry → scripts, run command, workflow files, executor; plus
  `[package]` globs for the shared library that every code manifest
  covers. Unbound entries follow the `scripts/<entry>.py` convention.

The spec files themselves carry YAML frontmatter (`name`, `kind`,
`tier`, `consumes`, `references`) and `### entry` blocks declaring
each entry's `Output:` / `Export outputs:`. The whole file,
frontmatter included, is the contract — any edit returns its entries
to *audit needed*. No `Script:`, no `Status:`: bindings live in
`bindings.toml`, status is derived. See
[`src/specthis/templates/specs/README.md`](src/specthis/templates/specs/README.md)
for the full convention (the bundled templates ship a research/paper
instantiation — compute entries producing JSON, report entries
exporting `.tex` into a host document — but the ledger model is
domain-general).

## Install

```bash
pip install specthis          # core: CLI + agent templates
pip install "specthis[s3]"    # adds the remote (S3) cache backend (stub)
```

Or with [uv](https://docs.astral.sh/uv/) — no install needed, works from
any directory:

```bash
uvx specthis serve            # run straight from PyPI
uv tool install specthis      # or install a persistent `specthis` command
```

From a clone of this repo, `uv run specthis <command>` (at the repo root)
builds the local source and runs it.

The dashboard serves on `127.0.0.1:8765` by default; pass
`--port`/`--host` to `specthis serve` if that port is taken.

## Scaffold a project

```bash
specthis install    # writes the Claude Code subagents into .claude/agents/
specthis init       # creates specs/ with README.md + AGENTS.md templates
```

Three Claude Code subagents cover the daily operations:

- **`spec-auditor`** — runs `specthis check`/`status` for the
  mechanical layer, judges contract-in-spirit for entries on the
  frontier, and *proposes* verdicts. It never vouches.
- **`spec-implementer`** — authors code for an unimplemented entry,
  binds it, smoke-tests it, then stops and proposes the vouch. It
  authored the change, so the pen is not its.
- **`experiment-runner`** — launches a long run in the background
  (preferring `specthis run <entry>` so the claim is recorded),
  watches the log, reports completion.

## Migrating from the old `_lock.json`

```bash
specthis migrate            # dry-run report
specthis migrate --write    # import run rows
```

Old certified inputs import as derived claims only — **no vouches
migrate**, by design: judgment does not transfer from a hash file.
Post-migration everything reads *audit needed* or *stale*, and the
humans work the queue with `specthis vouch` / `specthis run --stale`.

## Roadmap

Done: spec/bindings parsing, content hashing + composed signatures,
both ledgers, status derivation + frontier, the five verbs, migration,
scaffolding, agent templates, the dashboard (`export` + `serve` with
live reload, stdlib only), host-doc routing (`_routing.json` +
orphaned-export checks), and the remote cache (`file://` and `s3://`
backends, digest-verified fetch keyed by the composed signature).

Known future extensions — each additive, none precluded by the core:
output-schema-into-signature, quick-tier caching as an executor
concern, section-scoped spec hashing if whole-file contract hashing
ever causes too much re-judgment churn.

## License

MIT — see [LICENSE](LICENSE).
