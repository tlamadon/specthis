---
name: README
kind: meta
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
run, or whether its output exists. Those are claims about the current
state of the repo, and claims live in the two ledgers next to the
specs — `vouches.toml` and `runs.toml` — never inside a spec.

## Mental model

**specthis is a notary for a DAG it also knows how to build.** One
ledger (two TOML files, versioned in git) records claims about the
project. Its job is to answer, cheaply and at any moment: which claims
are still true, and what kind of repair does each broken one need?

**The claim unit is the entry** — one script(-set), one output, one
deliverable. A spec file is a bundle of entries plus the prose contract
they are judged against. Multi-entry specs get multiple ledger rows;
nothing is claimed at file or project granularity.

**Two species of claim, verified in opposite directions.** *Attested*
claims (spec ↔ code, in `vouches.toml`): someone who did not author the
change judged that this code satisfies this contract, at these digests.
Verification looks backward — are the blobs unchanged since the vouch?
*Derived* claims (code → artefact, in `runs.toml`): this artefact came
from this code on these exact inputs. Verification looks forward —
re-derive the composed signature (scripts + package blob + upstream
artefact digests + workflow config) and compare. Judgment cannot be
computed; computation need not be judged.

**Claims are shallow; trust propagates.** A vouch covers only the
entry's own blobs, never its dependencies' contents. When something
upstream moves, downstream vouches do not expire — they get flagged.
`specthis check` walks the DAG and diagnoses, per entry, which repair
is needed:

- **audit needed** — your own spec or code moved (or was never judged);
  re-judge, then vouch.
- **rejected** — a judge said no at exactly these digests; something
  must change.
- **stale** — inputs moved, or output bytes were edited in place;
  re-run. Machine work, no judgment.
- **upstream-unverified** — your claim stands but rests on ground that
  moved; fix upstream and this heals for free.

Absent bytes are none of these. An entry whose claim stands but whose
declared outputs are not on this disk reads **ready** marked *bytes
remote* — a byte-locality fact, not a break. Nothing recomputes it,
downstream signatures still compose (they read the recorded digest),
and `specthis cache fetch <entry>` materializes the bytes — verified
against the claim — if and when they are actually needed.

Re-judge, re-run, or look upstream — and the tool never confuses the
three.

**Two kinds of edge, only one carries trust.** `consumes:` edges are
artefact flows: they enter signatures and propagate status.
`references:` edges are vocabulary (models, estimators, conventions):
documentation for readers and agents, invisible to the ledger. A
`definitions` hub can be edited without detonating the certificate
graph.

**The pen is guarded.** `vouch` is its own command, records who
attested, and is never run by the author of the change — human or
agent. `run` writes derived claims freely; `check` and `status` write
nothing; neither ever touches an attested claim.

**Below the ledger, specthis decides what runs; executors decide how.**
Stale intensive entries hand off to scripthut (whose fingerprint is an
ingredient of the signature, never a certificate); quick entries
rebuild locally. Throughout: git holds claims, caches hold bytes,
digests join them. Delete every cached byte on every machine and the
ledger still says exactly what was true and what must happen — by
machine or by judgment — to make it true again.

In one breath: specs promise, code delivers, artefacts are receipts,
and specthis is the ledger that tells you — per deliverable — whether
the promise still holds, and whether fixing it needs a mind, a machine,
or just patience while upstream heals.

## The three state files (all in git, all human-readable)

| File | Holds | Written by |
|---|---|---|
| `specs/vouches.toml` | attested claims: `(spec_sha, code_sha, verdict, attester, when, note)` per entry | `specthis vouch` — only |
| `specs/runs.toml` | derived claims: composed input signature, output digest, executor, and the full `[inputs]` table per entry | `specthis run` — only |
| `specs/bindings.toml` | entry → scripts, run command, scripthut workflow files, executor; plus `[package]` globs for the shared library and `[preview]` recipes for the dashboard | you, by hand |

`bindings.toml` is vocabulary, not a claim: it says *where* an entry's
code lives and *how* to run it. Pointing an entry at different code
moves its code manifest, which expires its vouch automatically. If an
entry has no binding, the convention `scripts/<entry>.py` (run with
`python`) is assumed:

```toml
[package]
globs = ["src/mypkg/**/*.py"]     # the shared library every code manifest covers

[cache]
url = "s3://my-bucket/myproject"  # optional remote byte cache (or file:///path);
                                  #   `specthis run --stale --fetch` pulls verified
                                  #   bytes instead of recomputing

[entries.fit-alpha]
scripts   = ["scripts/fit_alpha.py"]
run       = "python scripts/fit_alpha.py"
workflows = ["hut.fit-alpha.json"]   # scripthut config: signature input, not judged code
executor  = "scripthut:slurm"        # omit for local execution
```

### Previews (dashboard-only)

When served (`specthis serve`), declared outputs are viewable at
`/view/<path>`: text escaped and highlighted, images and PDFs as-is.
A `[preview]` table teaches the dashboard to *render* an output type
— same division of labor as executors: specthis provides the plumbing
(when to render, where to cache, what to serve), your recipe provides
the how. Recipes are a view concern: rendered artifacts are cached
outside the repo, content-addressed by (output bytes, recipe, declared
inputs), and never read back by the ledger.

```toml
[preview.".tex"]
command = "scripts/preview_tex.sh {input} {host_doc} {out}"  # runs at the project root
format  = "pdf"                                   # what lands at {out} (default pdf)
inputs  = ["paper/preamble.tex", "scripts/preview_tex.sh"]  # part of the cache key
```

The command must place its artifact at `{out}`; `{input}` is the
output file (project-relative) and `{host_doc}` is the owning spec's
`host_doc:` (empty if none). Declare in `inputs` everything else the
render reads — the preamble, the recipe script itself — so editing
them invalidates exactly the affected previews. Successful renders are
cached; failures are not (the log shows in the browser; fix and
reload). A wrapper that compiles a fragment inside its host document's
preamble is about ten lines:

```sh
#!/bin/sh
# preview_tex.sh <fragment> <host_doc> <out>: compile a .tex fragment
# inside the host document's preamble, place the PDF at <out>.
set -e
frag="$1"; host="$2"; out="$3"
build=$(mktemp -d); trap 'rm -rf "$build"' EXIT
sed '/\\begin{document}/,$d' "$host" > "$build/wrapped.tex"   # host preamble
printf '\\begin{document}\n\\input{%s}\n\\end{document}\n' "$(pwd)/$frag" >> "$build/wrapped.tex"
TEXINPUTS=":$(dirname "$host"):" tectonic --outdir "$build" "$build/wrapped.tex" \
  || TEXINPUTS=":$(dirname "$host"):" pdflatex -interaction=nonstopmode \
       -no-shell-escape -output-directory "$build" "$build/wrapped.tex"
mv "$build/wrapped.pdf" "$out"
```

## Frontmatter convention

Every `.md` file in this directory begins with YAML frontmatter:

```yaml
---
name: <spec-name>          # filename stem, no extension
kind: <kind>               # see below
tier: intensive | quick    # compute specs; intensive is the default
skip: true                 # optional: comment this spec out (see below)
consumes:                  # upstream ENTRY names whose artefacts this
  - <entry-name>           #   spec's code reads — enters signatures
references:                # other spec FILES read for vocabulary —
  - <other-spec>.md        #   ledger-invisible
---
```

The entire file — frontmatter included — is the contract: any edit
returns the file's entries to *audit needed*. There is no `depends_on:`
(retired: it conflated the two edge kinds) and no `Status:` anywhere —
status is derived, never authored.

`skip: true` comments a spec out while developing: its entries leave
the frontier and every count, `run`/`vouch` refuse them, their ledger
rows stay but go dormant, and the body is not grammar-checked (a
half-written entry block is fine). The dashboard still renders the
spec, greyed and marked *skipped*. Anything that `consumes:` a skipped
entry becomes a lint problem — skip downstream too, or unwire the
edge. Honesty is content-addressed: a spec edited while skipped comes
back as *audit needed* (its bytes moved), while a pure skip/un-skip
round-trip restores the exact vouched bytes and trust returns with
them.

Valid `kind:` values:

| kind          | meaning |
|---------------|---------|
| `meta`        | About specs themselves: index, agent behaviour. |
| `definitions` | Pure vocabulary other specs reference (conventions, notation). No entries — and therefore invisible to the ledger; use `library` when the vocabulary is implemented by code. |
| `library`     | Contracts on **package code with no artefact** — the chain stops at code. Entries carry no `Output:`; each MUST be bound to its module(s) in `bindings.toml` (no convention default). Status ladder stops at the vouch: a library entry is *ready* when a non-author vouched it at the current digests. Consumable: downstream `consumes:` edges take its code manifest as the upstream digest, so a module edit flags the entry *audit needed* and makes its consumers *stale*. Library-bound modules are carved out of the `[package]` blob. |
| `templates`   | Reusable table / figure patterns: palette, layout, reference implementation. |
| `compute`     | Named entries with an `Output:` contract that produce JSON / data. Usually `tier: intensive`. |
| `report`      | Named entries with an `Export outputs:` contract that produce figures/tables; `host_doc:` + `section_label:` in frontmatter route the artefacts. Quick. |
| `figure`      | Standalone figure/table generator: same `Export outputs:` contract as `report`, but self-contained — no host doc, no routing. Quick. |

The `definitions` / `library` split answers "when does an edit get
picked up?": a `definitions` edit is picked up only when a human next
reads the file; a `library` edit is picked up by the ledger — the
entry returns to *audit needed* and everything consuming it waits on
the re-vouch.

## What a specification looks like

A spec is **an authoring contract on code**. Every compute / report /
figure spec is organised around two complementary parts:

- **`## Script`** (compute) or the per-entry export prose (report) —
  *prose about how to author the code*: the data loader, model
  factory, fit loop, exporter routines. Part of the contract; names no
  path.
- **`## Entry`** (single) or **`## Entries`** (multi) — the claim
  unit(s). Each `### entry-name` block carries:
  - `Output:` (compute — exactly one path, e.g.
    `` Output: `results/alpha/fit.json` ``) or `Export outputs:`
    (report/figure — one or more paths, inline or as a `- ` list).
    This is the artefact the entry promises: the public interface
    downstream `consumes:` edges depend on.

An entry carries **no** `Script:` (that is `bindings.toml`) and **no**
`Status:` (that is derived). On the report side, an entry additionally
carries an **`## Artefact design`** block pinning layout / palette /
caption — that layout is part of the contract.

A spec file does **not** carry result numbers. Point estimates,
standard errors, log-likelihoods — those live in the result files at
the output paths the spec declares. The spec stays stable as a
contract; the results layer evolves independently.

## File-naming convention

Files are named after the noun being specified: `models.md`,
`estimators.md`, `compute-<job>.md`, `report-<job>.md`. Each workflow
is split across two files — `compute-<name>.md` for the fit,
`report-<name>.md` for the export + routing — paired by shared stem.

## The five verbs

```bash
specthis check                 # the frontier: local breaks itemized,
                               #   downstream summarized; non-zero exit on any local break
specthis status [entry]        # every entry's status / one entry in detail,
                               #   including WHICH input moved
specthis run <entry>           # resolve + record upstream digests, dispatch
                               #   (local or scripthut per bindings), write runs.toml
specthis run --stale           # rebuild every machine-repairable entry in dependency order
specthis vouch <entry> --as NAME [--reject] [--note TEXT]
                               # attest — someone other than the author, always named
specthis serve                 # live dashboard (a regenerated view; writes nothing,
                               #   and the ledger never reads it)
```

Two more verbs cover **remote compute whose bytes should stay put**
(HPC results too big to bring home). Requires a configured `[cache]`:

```bash
specthis manifest <entry>      # ON THE MACHINE THAT RAN IT: certify the bytes —
                               #   upload tarball + manifest under the composed signature
specthis run <entry> --adopt   # ON THE LEDGER MACHINE: record the runs.toml row
                               #   from that manifest; no bytes move
```

Adoption is self-verifying: the ledger machine composes the expected
signature from its own tree and looks the manifest up at exactly that
key, so a drifted tree (unpushed edits, wrong branch) finds nothing.
The adopted entry reads *ready (bytes remote)*; consumers fetch on
demand. For chains run remotely in one workflow, `manifest` each
entry in dependency order there, then `--adopt` in the same order
here.

`check` and `status` never write. `run` never touches `vouches.toml`.
`vouch` never touches `runs.toml`. A rejection binds at its exact
(spec, code) digest pair: `vouch` refuses an `ok` over a standing
rejection until something changes. No command consults mtime, ever —
a fresh clone on another machine gives identical answers.

## How to add a new spec file

1. Name the file after the noun being specified; add the frontmatter
   block with the right `kind:`, `consumes:`, and `references:`.
2. For executable kinds, give each entry a contract and an `Output:` /
   `Export outputs:` — but no `Script:` / `Status:`.
3. Bind the entry in `specs/bindings.toml` (or follow the
   `scripts/<entry>.py` convention).
4. Author the code, have someone who didn't author it run
   `specthis vouch <entry> --as <name>`, then `specthis run <entry>`.
   From then on `specthis check` tells everyone whether the claim
   still holds.
