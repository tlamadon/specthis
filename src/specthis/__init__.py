"""specthis — spec-driven research workflow tooling."""

from importlib.metadata import PackageNotFoundError, version

try:
    # One source of truth: pyproject. Declaring the version twice is how
    # `specthis --version` spent three releases reporting 0.0.32.
    __version__ = version("specthis")
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0+unknown"
