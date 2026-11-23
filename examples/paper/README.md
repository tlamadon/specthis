# A worked example: the paper is the last link

[`../wages`](../wages) ends at bytes: a table lands in `reports/`, and
specthis can say whether it came from code a mind judged. But the thing a
research project ships is the **manuscript**, and it sits one link past
the end. Two claims have no subject there — *the paper prints what the
artefact holds*, and *the paper describes what the spec says* — and a
result the paper prints that nothing produced is invisible, because
specthis walks from what you declared.

This example makes the paper a terminal node of the graph: one table and
one proposition, each an **exhibit** entry. Every command below is
executed by `tests/test_example.py`.

```
specs/wages.md        a source and two computes — the numbers
specs/paper.md        two exhibits — what the paper prints
specs/bindings.toml   the map, plus [documents.paper]: where the manuscript lives
pipeline.toml         two steps; exhibits never have one
paper/paper.tex       the manuscript: one table, one proposition, one figure
```

Run everything from this directory.

---

## 1. An exhibit

```markdown
### tab-moments

Table 1: the log wage moments by year, laid out as `moments-table`
renders them. The caption and note must describe the procedure
`wage-moments` defines — non-positive wages dropped, the population
variance of log wages.

- consumes: wage-moments, moments-table
- appears: paper#tab:moments
```

`appears` and no `produces`: that is the whole type. It makes nothing,
has no code, and has no pipeline step. `paper#tab:moments` addresses a
**span** of a document: `paper` is declared in the map —

```toml
[documents.paper]
path         = "paper/paper.tex"
environments = ["table", "figure", "proposition"]
unbacked     = ["fig:flow"]
```

— and `tab:moments` is the `\label` inside the table. The span is the
innermost environment around the label, `\begin{table}` … `\end{table}`:
caption, note and body as printed.

A contract names the document, never its path. Move the manuscript and
you edit one line of `bindings.toml`; nothing expires.

## 2. Look before you touch

```bash
specthis lint
```

`lint` is also the **orphan detector**. Every label of a configured
environment class must be claimed by an exhibit or listed as `unbacked`
— `fig:flow` is a schematic, so nothing computed backs it, and it says
so. Delete that `unbacked` line and lint names it.

## 3. Build, and judge

```bash
specthis record raw-wages
specthis build
specthis vouch raw-wages     --as ana
specthis vouch wage-moments  --as ana
specthis vouch moments-table --as ana
```

That is the ordinary loop. Now the new judgment:

```bash
specthis status tab-moments
```

```
appears:   paper#tab:moments  ->  paper/paper.tex:13-20 (table)
```

A critic reads exactly those lines, and the contracts of the entries the
exhibit consumes, and attests that **the paper describes the result the
way those contracts define it**. Reading, never running — and no code is
read at all:

```bash
specthis vouch tab-moments --as ben
specthis vouch prop-units  --as ben
specthis check                       # ready: 5/5
specthis status
```

```
vouch tree  5/5 certified
run tree    3/3 current
paper       2/2 described         +1 unbacked
```

Exhibits live on the vouch tree only — like a library, they have no
bytes of their own — and the document gets a line of its own: how much of
what it prints is described, and how much nothing backs.

---

## 4. What expires, and what does not

### Reflow a paragraph, or add a comment

Co-authors reflow text constantly. The span digest collapses whitespace
and drops LaTeX comments the way TeX does, so neither moves it:

```bash
specthis check    # ready: 5/5 — nothing expired
```

### Edit the paper outside every span

The section's opening prose belongs to no exhibit. Edit it and nothing
expires — a vouch pins its span, not the file.

### Edit the table's note

Change "dividing by $n$, not $n-1$" to "dividing by $n-1$":

```
vouch tree — definitions needing a mind:
  unvouched      tab-moments    moved since vouch: ~doc:paper#tab:moments
```

One exhibit, mind queue only. The critic reads it and disagrees:

```bash
specthis vouch tab-moments --as ben --reject \
  --note "the note says n-1; wage-moments defines the population variance"
```

That rejection **is the discrepancy list** an audit used to keep by
hand — recorded, attributed, and binding at exactly these digests: an
`ok` is refused until the span or a contract it consumes moves. The
repair is a decision, not a rerun — fix the paper, or change the
computation. Fix the note, and the rejection lifts:

```bash
specthis vouch tab-moments --as ben    # the span moved; judged again
```

### Edit a contract the paper describes

Tighten `wage-moments`' prose in `specs/wages.md`:

```
  unvouched      prop-units     moved since vouch: ~spec:wage-moments
  unvouched      tab-moments    moved since vouch: ~spec:wage-moments
  unvouched      wage-moments   moved since vouch: spec: this entry's block in wages.md moved
```

An exhibit's vouch pins each consumed entry's **contract**, so when what
a result *means* changes, every description of it in the paper is due
for a re-read — and no machine is asked for anything.

### Print a table nothing produced

Add a table typed by hand, and lint names it:

```
warning: paper (paper/paper.tex:…): table `tab:extra` is claimed by no exhibit — …
```

```
paper       2/2 described         1 orphan   +1 unbacked
```

That is the orphan detector: a result the paper prints that no declared
entry backs. Only the manuscript can enumerate those.

---

## What is not here yet

The exhibit's *mind* claim ("described") is built. Its optional
*machine* claim — a checker that compares the printed numbers with the
artefact ("printed"), a `failed` state for "ran and disagrees", and
formal statements (a Lean theorem) as backing — are the next steps in
[`docs/specification.md`](../../docs/specification.md) §17.
