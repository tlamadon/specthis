# specthis

A spec-driven research workflow: a dashboard, Claude Code subagents, and
a refresh/cache pipeline for projects that produce reproducible compute
artefacts (typically JSON) and assemble them into a LaTeX (or similar)
report.

> Status: **early scaffold**. The CLI shell and the agent / spec
> templates work. The dashboard renderer, lock manager, S3 cache, and
> refresh orchestrator are stubs awaiting porting from the reference
> implementation. See [Roadmap](#roadmap).

## What it is

A small package that gives a research project:

1. **A spec format.** Each `compute-*.md` / `report-*.md` file in
   `specs/` declares the path of a script that produces a JSON
   artefact (compute) or a LaTeX figure / table (report), plus a
   `Status:` line that pins whether the script satisfies the
   contract.
2. **A dashboard.** `specs/specs.html` renders the directory as a
   browsable view of entries, their statuses, the produced
   artefacts, and the cross-references between compute outputs and
   report inputs.
3. **A content-hash lock.** `specs/_lock.json` records the hash of
   each entry's spec + script content at the moment it was certified
   `script ready`. The refresh orchestrator refuses to rerun an
   entry whose spec or script has drifted from the certified hash
   without an explicit re-audit.
4. **Three Claude Code subagents.** Drop-in agents for the three
   operations a human or LLM does daily on a spec directory:
   - `spec-auditor` — read-only consistency check (operation 1).
   - `spec-implementer` — author a missing script for a
     `script TBD` entry (operation 3).
   - `experiment-runner` — kick off a long-running script in the
     background, monitor its log for milestones / errors, report
     completion.
5. **(Optional) An S3 compute cache.** Push the `results/<entry>/`
   directory to S3 keyed by the spec's `inputs_certified` hash, so
   collaborators can pull instead of re-running.

## Install

```bash
pip install specthis        # core: CLI + agent templates
pip install "specthis[s3]"  # adds the S3 cache backend
```

## Scaffold a project

In any project directory:

```bash
specthis install            # writes the three agents into .claude/agents/
specthis init               # creates specs/ with README.md + AGENTS.md templates
```

After `init`, edit `specs/README.md` and add your first
`compute-<name>.md` / `report-<name>.md` pair.

## CLI

```
specthis install    Copy agent templates into <cwd>/.claude/agents/
specthis init       Create specs/ skeleton (README.md + AGENTS.md)
specthis audit      Run the consistency audit (stub — port pending)
specthis refresh    Rerun stale entries respecting the lock (stub — port pending)
specthis serve      Start a local dev server for specs.html (stub — port pending)
specthis lock       Manage the content-hash lock file (stub — port pending)
```

## The spec format in one paragraph

Every spec file under `specs/` carries YAML frontmatter
(`name`, `kind`, `depends_on`) and one of two body shapes:

- **`kind: compute`** — a `## Script` prose section describing how
  the script is laid out, plus one or more `### entry-name` blocks
  each carrying `Script:`, `Output:` (a JSON path), and `Status:`.
- **`kind: report`** — same shape, but per-entry fields are
  `Export script:`, `Export outputs:` (LaTeX paths), and `Status:`,
  plus frontmatter `host_doc:` and `section_label:` that route the
  artefacts into a section of a top-level `.tex` document.

`Status:` is `script TBD` (the script does not satisfy the contract)
or `script ready` (it does, and a smoke-test passed). The
`scripts ran` vs `outputs exist on disk` axis is observed by the
auditor and the dashboard — it is not part of the spec.

See `src/specthis/templates/specs/README.md` for the full convention.

## Roadmap

The reference implementation (a ~7000 LOC private codebase) is being
ported into this package one module at a time. Order:

1. **agent templates + spec format docs** — done (this scaffold).
2. **`specthis install` / `specthis init`** — done.
3. **`specthis audit`** — port the index-based auditor.
4. **`specthis serve`** — port the HTML dashboard renderer +
   `_index.json` / `_routing.json` exporter.
5. **`specthis lock`** — port the content-hash lock manager.
6. **`specthis refresh`** — port the Makefile-driven refresh
   orchestrator.
7. **`specthis cache`** — port the S3 backend.

Each module ships with a config-driven surface (paths configurable
via `specthis.toml`), no hard-coded assumptions about the host
project's layout beyond the defaults documented in the spec format.

## License

MIT — see [LICENSE](LICENSE).
