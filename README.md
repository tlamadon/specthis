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
> and host-doc routing, the journal view, and the remote cache. See
> [Roadmap](#roadmap) for the deliberately-deferred extensions.

## The model

**The claim unit is the entry**: one script(-set), one output, one
deliverable. A spec file is a bundle of entries plus the prose
contract they are judged against. The exception is `kind: library` —
entries whose chain *stops at code* (package modules with no
artifact): they carry only the attested claim, are `ready` once
vouched at the current digests, and contribute their code manifest as
the upstream digest to whatever consumes them — so editing a library
spec or module flags exactly that entry for re-judgment and exactly
its consumers for re-run, instead of detonating every vouch through
the package blob.

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
specthis lint      # grammar check: EVERY problem across all files at once
specthis export    # write specs/specs.html + _index.json + _routing.json
specthis serve     # live dashboard at localhost:8765; re-renders on any
                   # spec / ledger / code / output / host-doc change (writes nothing)
```

Readers are lenient, writers are strict: `check`, `lint`, and the
dashboard load whatever parses and *surface* the grammar problems (in
the page, in a red "does not parse" sidebar group with the broken
file's markdown still rendered best-effort, and in `check`'s output —
which exits non-zero on problems). `run`, `vouch`, and `migrate`
refuse to write ledgers against a tree that doesn't parse. The
`/specthis-lint` slash command explains each problem and fixes the
mechanical ones.

When served, **text outputs are clickable**: an output chip whose bytes
are on disk and look like text opens at `/view/<path>` in a new tab —
escaped, syntax-highlighted (highlight.js from CDN, plain text
offline), and restricted to declared outputs. In the static
`specs.html` opened from disk there is no server, so the chips degrade
back to plain text.

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

When an entry runs **where the bytes should stay** (an HPC cluster, a
collaborator's machine), the claim still travels without them:

```bash
specthis manifest <entry>       # ON THE MACHINE THAT RAN IT: certify + upload
                                #   tarball + manifest under the composed signature
specthis run <entry> --adopt    # ON YOUR MACHINE: record the runs.toml row
                                #   from that manifest — no bytes move
```

Adoption is self-verifying: your machine composes the expected
signature from its own tree and looks the manifest up at exactly that
key — a drifted tree finds nothing. The adopted entry reads *ready*
with its bytes marked remote (`check` names it; absence is not
staleness — only edited bytes or moved inputs are stale), and anyone
who actually needs the bytes is one verified `cache fetch` away.

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

**Route the audit queue: humans judge intent, agents read drift.**
A vouch binds an exact `(spec_sha, code_sha)` pair, so *audit needed*
on a previously-vouched entry splits into two lanes. If the **spec**
moved, the contract itself changed — re-judging the code against new
intent is human work. If only the **code** moved, the contract is
stable and the question is drift against a fixed target — exactly
what the `spec-auditor` is built to read; its proposal gets stamped
cheaply with `vouch --as`, attention reserved for the contract lane.
Never-vouched entries (a fresh migration, say) have no pair to diff,
so the first pass through the queue is all human-grade judgment —
and it's that baseline that makes later drift legible and delegable.

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

## Journal

Alongside the claims lives the narrative: `journal/` at the project
root holds dated entries, one markdown file per story —

```
journal/2026-06-30-smc-ffbs-resampling-fix.md
journal/2026-06-10-abb-calibration-and-lom-fits.md
```

A journal entry is prose, not a claim: the ledger neither reads nor
hashes it, no status depends on it, and there is nothing to vouch.
It records what the ledger cannot — why a result looks the way it
does, which alternatives died and how, the numbers behind a decision.
Small shareable artefacts (a JSON bundle, a figure) can be committed
next to their entry so they stay downloadable even when the results
directory is gitignored.

The dashboard picks the directory up automatically: a journal group
in the sidebar, a filterable card index (date + title), and one page
per entry with the narrative rendered. Markdown links cross the two
worlds in both directions — a spec linking
`journal/2026-06-30-….md` and an entry linking
`../specs/compute-alpha.md` both become hash-routed links in the
page. The date comes from the filename prefix, the title from the
first `#` heading (or frontmatter `title:`).

The `/specthis-journal [topic]` slash command (installed by
`specthis install`) writes an entry from the current Claude Code
session: what was attempted, what was decided and why, the dead ends
worth remembering, with links to the specs involved.

## Scaffold a project

```bash
specthis install    # writes the Claude Code subagents into .claude/agents/
specthis init       # creates specs/ with README.md + AGENTS.md templates
```

Four Claude Code subagents and the slash commands cover the daily
operations:

- **`spec-auditor`** — runs `specthis check`/`status` for the
  mechanical layer, judges contract-in-spirit for entries on the
  frontier, and *proposes* verdicts. It never vouches.
- **`spec-implementer`** — authors code for an unimplemented entry,
  binds it, smoke-tests it, then stops and proposes the vouch. It
  authored the change, so the pen is not its.
- **`experiment-runner`** — launches a long run in the background
  (preferring `specthis run <entry>` so the claim is recorded),
  watches the log, reports completion.
- **`spec-critic`** + **`/specthis-vouch [entries…]`** — the one
  sanctioned agent pen. The slash command is your explicit
  commission (your name comes from `git config user.name`): it spawns
  the critic as a *fresh* session that authored nothing, which
  re-reads spec and code from disk, vouches clear passes as
  `spec-critic (for <name>)` (so the ledger shows the judgment was
  agent-made and who asked for it), rejects clear violations, and
  leaves every doubt unvouched for you. Independence here is
  contextual, not personal — the ledger records exactly that.
- **`/specthis-run [entries…]`** — the machine half: rebuilds the
  stale queue in dependency order (`run --stale`, with `--fetch` when
  a cache is configured), backgrounds and monitors intensive entries
  instead of blocking, and reports what was rebuilt, fetched, and
  skipped as needing a mind. Together the two commands split the
  frontier by repair kind: `/specthis-vouch` for minds,
  `/specthis-run` for machines.
- **`/specthis-journal [topic]`** — the narrative pen: writes a dated
  entry into `journal/` from the current session (see
  [Journal](#journal)). No ledger is touched — the journal records
  the why, the ledgers record the what.

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
orphaned-export checks), the remote cache (`file://` and `s3://`
backends, digest-verified fetch keyed by the composed signature), and
the journal (`journal/` narratives rendered into the dashboard, plus
`/specthis-journal`).

Also done: **`skip: true` in frontmatter** — comment a spec out while
developing. Skipped entries leave the frontier and every count;
`run`/`vouch` refuse them; their ledger rows stay dormant; the body is
not grammar-checked; consuming a skipped entry is a lint problem; the
dashboard renders the spec greyed and marked *skipped*. Honesty is
content-addressed: a spec edited while skipped comes back as *audit
needed* (its bytes moved), while a pure skip/un-skip round-trip
restores the exact vouched bytes and trust returns with them.

Known future extensions — each additive, none precluded by the core:

- **Output-schema-into-signature.**
- **Quick-tier caching** as an executor concern.
- **Section-scoped spec hashing** if whole-file contract hashing ever
  causes too much re-judgment churn.

## License

MIT — see [LICENSE](LICENSE).
