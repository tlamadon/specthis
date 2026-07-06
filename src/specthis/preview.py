"""Output previews: project-declared recipes, rendered on view.

A ``[preview]`` table in ``specs/bindings.toml`` maps an output suffix
to a shell command that turns those bytes into something a browser
shows — typically a ``.tex`` fragment compiled inside the paper's
preamble:

    [preview.".tex"]
    command = "scripts/preview_tex.sh {input} {out}"
    inputs  = ["paper/preamble.tex", "scripts/preview_tex.sh"]

The command runs at the project root with two substitutions:
``{input}`` (the output, project-relative) and ``{out}`` (the cache
path its artifact must land at, suffixed per the recipe's ``format``).
specthis contributes the plumbing — which files, when to rerender —
and the project contributes what only it knows: how to compile them.

Everything here is a view concern, same trust story as executors: the
recipe is a configured ingredient, never an authority. Artifacts are
content-addressed by (output bytes, recipe, declared inputs) and
cached *outside* the project tree, so ``serve`` still writes nothing
into the repo; nothing rendered is ever read back by the ledger.
Successes are cached (unchanged inputs never recompile); failures are
not, so a fixed preamble or a returning binary heals on the next view.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import hashing

if TYPE_CHECKING:  # import cycle: parse.py validates formats against us
    from .parse import PreviewRecipe, Project

#: recipe ``format`` -> Content-Type the artifact is served with.
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "html": "text/html; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}

_TIMEOUT_SECONDS = 120  # a preview is a view; a hung compile must not wedge serve


def default_cache_dir() -> Path:
    """Where rendered artifacts live: outside the project tree, always.

    ``SPECTHIS_PREVIEW_CACHE`` overrides. Keys are content-addressed,
    so sharing one cache across projects is correct by construction.
    """
    env = os.environ.get("SPECTHIS_PREVIEW_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "specthis" / "previews"


def find_recipe(project: Project, rel: str) -> PreviewRecipe | None:
    """The recipe declared for this output's suffix, if any."""
    return project.previews.get(Path(rel).suffix.lower())


def preview_key(project: Project, rel: str, recipe: PreviewRecipe) -> str | None:
    """Content address of the rendered artifact; None if bytes are absent.

    Folds in everything the render depends on — output bytes, command,
    format, and each declared input's digest — so editing the
    preamble invalidates exactly the previews that read it, and nothing
    recompiles when nothing moved.
    """
    out_sha = hashing.file_sha(project.root / rel)
    if out_sha is None:
        return None
    pairs = [
        (f"output:{rel}", out_sha),
        ("command", hashing.sha256_text(recipe.command)),
        ("format", recipe.format),
    ]
    for pattern in recipe.inputs:
        matches = [p for p in sorted(project.root.glob(pattern)) if p.is_file()]
        if not matches:
            pairs.append((f"input:{pattern}", hashing.MISSING))
        for p in matches:
            digest = hashing.file_sha(p)
            assert digest is not None
            pairs.append((f"input:{p.relative_to(project.root).as_posix()}", digest))
    return hashing.manifest_sha(pairs)


@dataclass
class Preview:
    """One render attempt: the cached artifact, or the log of the failure."""

    key: str
    path: Path | None  # None when the recipe failed
    log: str = ""
    cached: bool = False


def render_preview(
    project: Project,
    rel: str,
    recipe: PreviewRecipe,
    cache_dir: Path | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> Preview | None:
    """Return the cached artifact or run the recipe; None if bytes are absent.

    Builds into a scratch dir and renames into place, so concurrent
    requests for the same key both succeed and the cache never holds a
    half-written artifact.
    """
    key = preview_key(project, rel, recipe)
    if key is None:
        return None
    cache_dir = cache_dir or default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = cache_dir / f"{key}.{recipe.format}"
    if final.is_file():
        return Preview(key=key, path=final, cached=True)

    scratch = Path(tempfile.mkdtemp(prefix="build-", dir=cache_dir))
    out_tmp = scratch / f"preview.{recipe.format}"
    command = recipe.command.replace("{input}", shlex.quote(rel)).replace(
        "{out}", shlex.quote(str(out_tmp))
    )
    try:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=project.root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return Preview(key=key, path=None, log=f"timed out after {timeout:g}s")
        log = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
        if proc.returncode != 0:
            return Preview(key=key, path=None, log=log or f"exit status {proc.returncode}")
        if not out_tmp.is_file():
            note = "command exited 0 but placed nothing at {out}"
            return Preview(key=key, path=None, log=f"{log}\n\n{note}" if log else note)
        os.replace(out_tmp, final)
        return Preview(key=key, path=final)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
