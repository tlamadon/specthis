# A worked example: the second country arrives

This is [`../wages`](../wages) after the moment every project reaches —
you need the same thing again, for a different dataset. Read that one
first if you have not; this assumes the loop and shows only what
templates change.

```
specs/wages.md        four entries — three of them templates
specs/bindings.toml   {country} placeholders in the product paths
pipeline.toml         five steps, declaring which countries exist
scripts/              the same code, taking a country argument
data/raw/{chile,argentina}/wages.csv
```

Run everything from this directory.

---

## What changed

One line, in three entries:

```markdown
- props: country
```

and a placeholder in the map:

```toml
[entries.clean-wages]
scripts  = ["scripts/clean_wages.py"]        # still concrete
produces = { wages-panel = "data/{country}/wages.csv" }
```

**`scripts` stays concrete.** Every instance runs the same code — that
is precisely what lets a single vouch cover the whole family.

## Where the instances come from

**The pipeline, and nothing else.** specthis performs no elaboration:
it reads the steps you wrote and matches each output against the
template's pattern.

```toml
[steps.clean-chile]
command = "python3 scripts/clean_wages.py chile"
deps    = ["scripts/clean_wages.py", "data/raw/chile/wages.csv"]
outs    = ["data/chile/wages.csv"]
```

`data/chile/wages.csv` matches `data/{country}/wages.csv`, binding
`country = chile`. **The step's name is irrelevant** — it is called
`clean-chile`, not `clean-wages@chile`, and nothing cares. Whatever
naming your compute manager generates will work.

The instance set is a function of committed files, because the pipeline
is one. There is no registry, and nothing to keep in sync.

## Run it

```bash
specthis lint
specthis record 'raw-wages[country=chile]'       # sources are pinned per instance
specthis record 'raw-wages[country=argentina]'
specthis build
```

```bash
specthis status
```

```
certified · current   raw-wages[country=argentina]     source
certified · current   raw-wages[country=chile]         source
certified · current   clean-wages[country=argentina]   compute/quick
certified · current   clean-wages[country=chile]       compute/quick
certified · current   wage-moments[country=argentina]  compute/quick
certified · current   wage-moments[country=chile]      compute/quick
certified · current   wage-comparison                  compute/quick
```

**Seven claims from four entries.** Instances are ordinary entries to
everything downstream: they have their own ledger rows, their own
staleness, their own bytes.

## One vouch, every instance

```bash
specthis vouch clean-wages --as ana
```

That covers `clean-wages[country=chile]` *and*
`clean-wages[country=argentina]`. It is the ceremony win — and it is
worth pausing on what you just signed:

> *this code is correct for **any** conforming country extract*

That is a universally quantified claim, and it is the strongest thing a
mind can be asked to sign. Sometimes it is true. When it is not:

```bash
specthis vouch 'clean-wages[country=chile]' --as ana
```

An instance vouch covers one instance, and wins over a template vouch
when both exist. Nothing declares which you meant — **you choose by
where you file it**, and you can change your mind later without touching
a spec.

## Two things worth trying

**Break one country.** Edit `data/raw/chile/wages.csv` and run
`specthis check`. Only the Chilean instances move; Argentina is
untouched, and `wage-comparison` waits on the one that broke.

**Add a third country.** Drop `data/raw/peru/wages.csv` in place, add
two steps to `pipeline.toml`, and run `specthis check`. Three new
instances appear. **No spec changes, no map changes** — and if you
vouched the templates rather than the instances, the new country arrives
already certified, because the claim you signed was about the code, not
about Chile.

That last sentence is the whole feature, and also the reason to be
careful about signing it.

## When to reach for this

Not on the first dataset. Write the second country by hand first — as if
templated — and promote when the difference really is only data. The
moment one country needs different *code*, demote it: drop `props`, give
it its own entry and its own `scripts`. The editorial end of a project —
figures, tables, the paper — usually stays hand-made forever.
