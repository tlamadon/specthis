# specthis

**A notary for a research pipeline.** It records who claimed what about
your project, and tells you which of those claims the content still
supports.

---

## Your project is a bakery

The **final goods** are cakes and pastries: your tables, your figures,
the paper that interprets them. The **raw materials** are flour and eggs
— data you did not produce, cannot certify, and can only source.

Between them is everything you actually build: a batter, a choux paste,
a crème pâtissière. Intermediates, each with a name, each held to a
standard, each feeding several things downstream.

You write three things, and keeping them separate is the whole idea:

| | |
|---|---|
| the **formula** — what each thing must be | a **spec**, in prose |
| the **method** — how it is actually made | your **code** |
| the **production sheet** — which method, which ingredients, which tray | a **pipeline** |

And two things get signed, by different people, at different moments:

- **The formula is approved once.** Someone makes it, cuts it open,
  judges it. That approval covers the next four hundred batches — and is
  void the instant the method changes or you rewrite the standard.
- **Every batch gets a label.** *Crème pât — 12 Aug — milk lot 88.* One
  per making. It survives nothing.

specthis keeps both pieces of paper, in git, and answers at any moment:
**which claims still hold, and what does each broken one need** — a mind
(re-judge), a machine (re-run), or patience (upstream will heal it).
The two never block each other: a batch can be remade while someone is
still deciding whether the formula was right.

**specthis makes nothing.** It never forks a process. Execution belongs
to a compute manager — the bundled runner, or one your project supplies.
specthis hands over the production sheet, reads what came back, and
countersigns it.

[`docs/analogy.md`](docs/analogy.md) tells this properly, in ten
minutes, including the failures and what each one needs.

## Start here

`pip install specthis` (or see [Install](#install) for uv), then read one
of the two worked examples — small enough to read in one sitting, and
executed by the test suite so they cannot drift from the tool:

- **[`examples/wages`](examples/wages)** — four workers, two years. The
  whole loop: record, build, vouch. Then it breaks the project twice to
  show the point — a prose edit moves one queue, a code edit moves both.
- **[`examples/wage-grid`](examples/wage-grid)** — the same project after
  the second country arrives. One formula, many batches: templates, and
  what a single vouch over a family actually claims.

Then [`docs/specification.md`](docs/specification.md) for what is
precisely true.

> Status: **implemented and tested**. See [Roadmap](#roadmap) for what is
> deliberately not built.

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
don't expire — they get flagged.

**Status is two coordinates, not one word.** The two claim species
become two status axes — one per ledger, one per tree — and each entry
sits on both; specthis derives them independently, neither gating the
other:

- **Certification** (the attested claim, the vouch tree — *is the
  definition judged?*): `unimplemented → unvouched → certified`, or
  `rejected`. A mind's claim about the (spec, code) pair; expires only
  when a digest moves.
- **Realization** (the derived claim, the run tree — *is the recorded
  call the one today's content implies?*): `never-run → stale →
  current` (absent for `library` entries, whose chain stops at code).
  A machine's claim about bytes.

So `specthis check` reports **two queues** — definitions needing a
mind, realizations needing a machine — with everything merely
downstream summarized per tree. An entry can sit in both (a mind
audits it while a machine reruns it), and the two queues drain in
parallel. The flattened single-word diagnosis — what `status`, the
dashboard, and older surfaces show — is derived from the pair, with
certification breaks winning:

| status | meaning | repair |
|---|---|---|
| `unimplemented` | no code on disk | author it |
| `audit needed` | your spec or code moved since the vouch (or was never judged) | a mind |
| `rejected` | a judge said no at exactly these digests | a mind |
| `stale` | inputs moved (or it never ran); the vouch stands | a machine |
| `upstream-unverified` | your claim stands on ground that moved | patience |
| `ready` | certified ∧ current, whole lineage | — |

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

**The notary never forks a process.** You author a pipeline in your
compute manager's own format; specthis reads it, hands over the whole
thing, and adopts the manifests that come back. A bundled runner ships
for projects with no manager of their own; anything implementing four
operations can replace it. git holds claims, the manager holds bytes,
digests join them. No mtime appears anywhere in ledger logic: a fresh
clone on another machine gives identical answers.

### Division of labor

Three roles, three pens — and only one of them is free-form:

| role | writes | via |
|---|---|---|
| **author** (you, or an implementer agent) | spec edits, code, and the binding in `specs/bindings.toml` (where the code lives, how to run it) | any editor |
| **critic** (a non-author: a colleague, you-next-week, a designated critic session) | attested claims in `specs/vouches.toml` | `specthis vouch --as` — only |
| **machine** | derived claims in `specs/runs.toml` | `specthis build` / `adopt` / `record` — only |

The author's pen is unguarded because nothing it writes becomes
trusted on its own: a binding edit changes which files the code
manifest covers, which expires the standing vouch — it can revoke
trust, never mint it. And when the critic vouches, the binding *and the
pipeline step* are swept into the judgment: they attest exactly the
files the binding names and exactly the command, inputs and outputs the
step declares. Realizing a spec means writing code **and** wiring it —
perfect code pointed at last year's data still fails the contract.
Author proposes, critic attests, a manager executes — and `check`
believes none of them without re-deriving the digests.

## The verbs

```bash
specthis check                 # the two queues (minds, machines); non-zero on any local break
specthis status [entry]        # both axes, and WHICH input moved
specthis lint                  # every problem at once: spec, map, and pipeline correspondence
specthis vouch <entry> --as NAME [--reject] [--note TEXT]
specthis build [entries…]      # hand the pipeline to the manager, adopt what comes back
specthis build <entry> --force # rebuild an artefact edited on disk
specthis record <entry>        # pin bytes no pipeline produced (a download, a one-off)
specthis adopt <entry> FILE    # countersign a manifest from a manager specthis did not launch
specthis adopted               # publish the steps your manager can skip (.specthis/adopted.json)
specthis certify               # code-identity certificates, if you use [package] globs
```

`adopted` is the answer back across the seam. When results are made
elsewhere — a cluster, a collaborator — `adopt` records that their bytes
are current, but your compute manager keeps its own bookkeeping and
would re-execute the step anyway, submitting jobs for work already on
disk and verified. So specthis publishes the ledger in the manager's
vocabulary: per step, the command and the dependency and output digests.
`build` republishes it before every handoff; run the verb yourself if
you drive make or snakemake directly. It is evidence, not an order — the
manager still decides, and a moved digest still means run the step.

Boundaries are load-bearing: `check`/`status`/`lint` never write,
`vouch` never touches `runs.toml`, and nothing but `vouch` touches
`vouches.toml`.

Three more render **views** — regenerated, never read back by the
ledger:

```bash
specthis export    # write specs/specs.html + _index.json
specthis serve     # live dashboard at localhost:8765; re-renders on any
                   # spec / ledger / code / output change (writes nothing)
specthis dag       # the spec-level DAG on stdout (or --out FILE): a standalone
                   # SVG figure (--view rails for the dashboard's git-log-style
                   # list), or --format json — nodes + both layouts + edges
```

The dashboard's sidebar is a **file tree**, read off the names in
`specs/`: a dot is a folder, so `compute.omega.weights.md` sits at
`compute › omega › weights.md`. Folders collapse (and stay collapsed
across live reloads), and every row carries its counts — how many
entries, how many need a mind, how many need a machine — with a folder
answering for everything under it. Renaming a file moves it; there is
no frontmatter that can disagree with where it lives.

Readers are lenient, writers are strict: `check`, `lint`, and the
dashboard load whatever parses and *surface* the grammar problems (in
the page, in a red "does not parse" sidebar group with the broken
file's markdown still rendered best-effort, and in `check`'s output —
which exits non-zero on problems). `vouch`, `record` and `migrate`
refuse to write ledgers against a tree that doesn't parse. The
`/specthis-lint` slash command explains each problem and fixes the
mechanical ones.

When served, **outputs are clickable**: an output chip whose bytes are
on disk opens at `/view/<path>` in a new tab — text escaped and
syntax-highlighted (highlight.js from CDN, plain text offline), images
and PDFs rendered natively — always restricted to declared outputs. In
the static `specs.html` opened from disk there is no server, so the
chips degrade back to plain text.

Outputs a browser can't show — a `.tex` table fragment, say — can be
**previewed** through a project-declared recipe in
`specs/bindings.toml`, the same division of labor as executors:
specthis provides the plumbing, the project provides the how.

```toml
[preview.".tex"]
command = "scripts/preview_tex.sh {input} {out}"
inputs  = ["paper/preamble.tex", "scripts/preview_tex.sh"]
```

The command runs at the project root and must place its artifact
(`format`, default `pdf`) at `{out}`; specthis substitutes `{input}`
(the output file) — so a ten-line wrapper can compile a fragment
inside the very preamble that will host it (the bundled
`specs/README.md` ships one). Previews are a view, never a claim: artifacts are
content-addressed by (output bytes, recipe, declared inputs), cached
*outside* the repo, rendered on first view at `/preview/<path>`
(linked from the `/view/` page), and never read back by the ledger.
Editing the preamble invalidates exactly the previews that read it. A
failing recipe shows its compile log in the browser — failures are
not cached, so fixing and reloading retries.

## Running the pipeline

You author the pipeline in your manager's own format — specthis reads
it and never writes it. Steps contribute four things: an id (the entry
name), a command, declared inputs, declared outputs.

The bundled runner reads `pipeline.toml`:

```toml
[steps.clean-wages]
command = "python src/clean_wages.py"
deps    = ["src/clean_wages.py", "config/clean.toml", "data/raw/wages.parquet"]
outs    = ["data/wages.parquet"]
```

Edges are derived, not declared twice: a step follows every step whose
`outs` its `deps` name. It walks the DAG and nothing else — no
parallelism, no resources, no remote, no retries. Wanting any of those
is the signal to point a real manager at the same declarations:

```toml
[backend]
class = "mypkg.adapters:ScripthutBackend"
```

Anything implementing `parse` / `submit` / `poll` / `manifests`
qualifies. specthis **never selects steps** — it hands over the whole
pipeline, because only the manager can know whether a rerun reproduces
identical bytes, or whether the work is already in its cache.

Every manifest is verified against the bytes on disk before it is
recorded. That proves *transcription*, not derivation: it catches a
garbled manifest, and it does not make a manager trustworthy —
establishing that outputs really came from that code would mean
re-running, which is the capability specthis does not have.

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
specthis build fit-alpha            # the manager runs it; specthis countersigns
specthis check                      # ready — and downstream entries now
                                    # show stale, ready for `specthis build`
```

**Did anything change?** The daily question — after a `git pull`,
after an editing session, or when you come back to the project after a
month. One read-only command answers it and names the repair:

```bash
$ specthis check
vouch tree — definitions needing a mind:
  unvouched      fit-beta        moved since vouch: code: fit_beta.py moved
run tree — realizations needing a machine:
  stale          fig-gamma       moved: upstream:fit-gamma
waiting on upstream: 3 (2 on minds, 1 on machines)
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
specthis build           # hand over the whole pipeline; the manager rebuilds
                         # what its content keys say is out of date
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
don't have to. Whatever reads *stale* is one `specthis build` away —
and whatever your manager already has cached costs nothing to restore.

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
  `(spec_sha, code_sha, verdict, attester, when, note)` per entry,
  plus the digests decomposed (`spec_block_sha`, per-file
  `code_manifest`) so an expired vouch is *attributed* — `check` and
  `status` say which script, the package blob, or where in the spec
  file moved — not merely detected. `vouch --took SECONDS` records
  what the judgment cost (claim metadata, moves no digest); the DAG
  views show each spec's last run/vouch age and duration.
- **`specs/runs.toml`** — derived claims: the composed signature, the
  output digest, the executor, the wall-clock `duration_seconds`
  (claim metadata — enters no signature), and the full `[inputs]`
  table (each script, workflow file, the package blob, and one
  `upstream:<entry>` digest per consumed artifact — so an upstream
  re-run is never invisible).
- **`specs/bindings.toml`** — the map: not a claim, and deliberately
  small. Two facts no pipeline format can express — `scripts` (which of
  a step's dependencies is *judged code*, the boundary between the two
  trees) and `produces` (which file **is** a logical product) — plus
  `[package]` globs for the shared library every code manifest covers.
  Everything about *how* a step runs lives in the pipeline. Unbound
  entries follow the `scripts/<entry>.py` convention.

A spec file is markdown. Each `### entry` block declares its own
interface as a field list:

```markdown
### clean-wages

Drop negative wages, winsorize at the 99th percentile via `winsor`.
One row per worker-year; no duplicates.

- consumes: raw-wages
- produces: wages-panel
```

Type is inferred from the fields — a bare `- code` is a library, a
physical path is a source, logical `produces` is computable, and
`- props: dataset` makes it a **template** whose instances the pipeline
declares. `kind:` and `name:` are optional; the older frontmatter form
still parses, so a project migrates at its own pace.

**A vouch pins the entry's own block**, not the whole file: editing a
sibling entry is somebody else's business. Display-only keys (`title`,
`group`, `priority`) are stripped before hashing, so retitling never
disturbs a vouch. No `Script:`, no `Status:`: the map holds bindings,
status is derived. See
[`src/specthis/templates/specs/README.md`](src/specthis/templates/specs/README.md)
for the full convention (the bundled templates ship a research/paper
instantiation — compute entries producing JSON, report entries
exporting `.tex` into a host document — but the ledger model is
domain-general).

## Install

```bash
pip install specthis          # core: CLI + agent templates
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
  (preferring `specthis build <entry>` so the claim is recorded),
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
- **`/specthis-run [entries…]`** — the machine half: hands the pipeline
  to the manager (`specthis build`), backgrounds and monitors long runs
  instead of blocking, and reports what was rebuilt, restored from
  cache, and left for a mind. Together the two commands split the
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
humans work the queue with `specthis vouch` / `specthis build`.

## Roadmap

**Done.** Spec and map parsing; content hashing, per-file tables and the
step digest; both ledgers; the two-tree status model (certification ×
realization, derived independently — `check` prints two queues, every
surface shows both axes); template entries with per-instance claims;
source entries and `record`; the pipeline reader, the bundled runner,
project-supplied backends, `build` and `adopt`; correspondence lint;
code-identity certificates; migration; scaffolding and agent templates;
the two-tree dashboard (`export` + `serve` with live reload — a
vouch-tree landing and a run-tree page plus an activity log, a
spec-level DAG with status rails, a layered figure and layout JSON via
`specthis dag`, stdlib only); the journal; and output previews.

Also done: **`skip: true` in frontmatter** — comment a spec out while
developing. Skipped entries leave every count and every queue; writers
refuse them; their ledger rows stay dormant; the body is not
grammar-checked; consuming a skipped entry is a lint problem; the
dashboard renders the spec greyed. Honesty is content-addressed: a spec
edited while skipped comes back as unvouched, while a pure skip/un-skip
round-trip restores the exact vouched bytes and trust returns with them.

**Deliberately not built.**

- **Parallel rebuilds, a byte cache, remote execution.** These left with
  the built-in executor in v0.1.0. A compute manager that has them
  supplies them; specthis does not reimplement half a scheduler.
- **One merged ledger.** `vouches.toml` and `runs.toml` stay two files.
  Collapsing them into a single record type changes no behaviour, and
  the payoff — a third capability landing free — has no third capability
  to land.

**Known future extensions** — each additive, none precluded by the core:

- **Adoption path: `specthis init --from-code`.** Kick-start an existing
  repo: walk `scripts/`, read what is already there (docstrings,
  filenames, imports), and *draft* spec files plus proposed bindings — a
  one-time extraction the human then edits. Drafts arrive unvouched, so
  the first pass is human-grade judgment. Specs remain the single home:
  docstrings seed the draft but are never read back by the ledger.
- **Output-schema-into-signature.**

## License

MIT — see [LICENSE](LICENSE).
