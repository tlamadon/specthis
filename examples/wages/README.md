# A worked example: four workers, two years

A complete specthis project small enough to read in one sitting. Nothing
here needs anything beyond Python's standard library, and every command
below is executed by `tests/test_example.py`, so it cannot drift from
what the tool actually does.

```
specs/wages.md        four entries: a source, two computes, a report
specs/bindings.toml   the map — judged code, and which file is which product
pipeline.toml         the production sheet — command, deps, outs
scripts/              the code
data/raw/wages.csv    eight rows, one of them a coding error
```

Run everything from this directory.

---

## 1. Look before you touch

```bash
specthis lint     # spec ↔ map ↔ pipeline all describe the same graph
specthis check    # nothing is claimed yet
```

`lint` is worth running first every time. It is what replaces a compiler
now that you author the pipeline by hand: it will tell you if an entry
has no step, if a step has no entry, if a `consumes` edge the contract
declares is not built, or if judged code is missing from a step's deps.

## 2. Pin the data that came from outside

`raw-wages` is a **source entry**. It has prose and a physical path, no
code and no pipeline step — nobody computed it, it arrived. Its bytes
enter the ledger by being recorded:

```bash
specthis record raw-wages
```

**Do this before building.** Downstream claims pin their upstream's
*recorded* digest, so a build that runs before the source is pinned
records a claim standing on nothing, and goes stale the moment you fix
it.

## 3. Build

```bash
specthis build
```

specthis hands the **whole** pipeline to a compute manager — here the
bundled runner — and the manager decides what actually needs running.
Every manifest that comes back is checked against the bytes on disk
before it is recorded.

```bash
cat reports/table.md
```

## 4. Judge it

```bash
specthis check    # every entry: current, and unvouched
```

The machine queue is empty; the mind queue holds everything. Nothing
has been *judged* yet — bytes exist, but no one has said the code does
what the prose promises.

```bash
specthis vouch raw-wages    --as ana    # provenance: this is the extract it claims to be
specthis vouch clean-wages  --as ana
specthis vouch wage-moments --as ana
specthis vouch wage-table   --as ana
specthis check                          # ready: 4/4
```

Note what `raw-wages` was vouched *for*. You cannot certify how someone
else produced a dataset; you attest **provenance** — that the file is
what it says it is.

---

## 5. The point of the whole thing

Now break it two different ways and watch the two queues move
independently.

### Edit prose only

Add a sentence to the `wage-table` block in `specs/wages.md`:

```
Four decimal places. Round half to even.
```

```bash
specthis check
```

```
vouch tree — definitions needing a mind:
  unvouched   wage-table   moved since vouch: spec: this entry's block in wages.md moved
ready: 3/4
```

**One entry, mind queue only.** The contract changed, so the judgment
expired — but no bytes moved, so nothing needs rebuilding. A
clarification costs zero compute.

And notice *only* `wage-table` moved. Three other entries share that
file and were untouched: a vouch pins the entry's own block, not the
whole file.

### Edit code

Change `round(m, 4)` to `round(m, 5)` in `scripts/moments.py`:

```bash
specthis check
```

```
vouch tree — definitions needing a mind:
  unvouched   wage-moments   moved since vouch: code: ~scripts/moments.py
  unvouched   wage-table     moved since vouch: spec: this entry's block in wages.md moved
run tree — realizations needing a machine:
  stale       wage-moments   moved: ~scripts/moments.py (unvouched)
ready: 2/4
```

**Both queues.** Code sits in both claims, so an edit expires the
judgment *and* invalidates the bytes. Two different people have work to
do, and neither waits for the other — the machine can rebuild while a
mind is still reading.

### Repair

```bash
specthis build                          # the machine's half
specthis vouch wage-moments --as ana    # the mind's half
specthis vouch wage-table   --as ana
specthis check                          # ready: 4/4
```

---

## What to try next

**Tamper with a product.** Edit `reports/table.md` by hand and run
`specthis check`. It reports the artefact no longer matches its record —
something a manager keying on *inputs* cannot see, because its inputs
did not move. `specthis build wage-table --force` repairs it.

**Move a file.** Change where `wage-moments` lands by editing one line
of `specs/bindings.toml` (`produces`) and one of `pipeline.toml`
(`outs`). The contract does not change, because the spec names a
*product*, not a path.

**Break the correspondence.** Delete a line from a step's `deps` and run
`specthis lint`. It will name exactly what the contract declares and the
pipeline does not build.

**Point it at a real manager.** The bundled runner walks the DAG and
nothing else — no parallelism, no cluster, no remote cache. When you
want those, write an adapter and name it in the map:

```toml
[backend]
class = "mypkg.adapters:ScripthutBackend"
```

Anything implementing `parse` / `submit` / `poll` / `manifests`
qualifies; nothing else in the project changes.

---

If the model still feels abstract, [`../../docs/analogy.md`](../../docs/analogy.md)
explains it as a bakery. For what is actually true,
[`../../docs/specification.md`](../../docs/specification.md).
