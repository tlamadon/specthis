"""Shared icon vocabulary for the rendered views.

Feather-style stroke icons on a 24px viewBox: terminal = compute job,
bars = report, book = library, open book = definitions, layout =
templates, info = meta, bolt = intensive tier. The sidebar pills
(:mod:`specthis.export`) and the DAG views (:mod:`specthis.dag`) draw
from the same dict so a kind always looks the same. Inline markup
only — the exported page and standalone SVGs stay self-contained.
"""

from __future__ import annotations

ICONS = {
    "compute": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "report": (
        '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>'
        '<line x1="6" y1="20" x2="6" y2="14"/>'
    ),
    "library": (
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
        '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
    ),
    "definitions": (
        '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
        '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>'
    ),
    "templates": (
        '<rect x="3" y="3" width="18" height="18" rx="2"/>'
        '<line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/>'
    ),
    "meta": (
        '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/>'
        '<line x1="12" y1="8" x2="12.01" y2="8"/>'
    ),
    "intensive": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
}


def svg_icon(name: str, x: int, y: int, size: int, color: str) -> str:
    """The icon as a positioned, scaled ``<g>`` fragment for SVG
    contexts — no nested ``<svg>``, and an explicit stroke color
    replaces CSS ``currentColor``. The scale also thins the 2.2 stroke
    to match the sidebar pills."""
    return (
        f'<g transform="translate({x},{y}) scale({size / 24:.4g})" '
        f'fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>'
    )
