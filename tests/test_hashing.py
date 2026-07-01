from pathlib import Path

from specthis import hashing


def test_signature_is_order_independent() -> None:
    a = hashing.signature({"x": "1", "y": "2"})
    b = hashing.signature({"y": "2", "x": "1"})
    assert a == b
    assert a != hashing.signature({"x": "1", "y": "3"})


def test_missing_sentinel_breaks_signatures(tmp_path: Path) -> None:
    manifest = hashing.files_manifest(tmp_path, ["gone.py"])
    assert manifest == {"gone.py": hashing.MISSING}


def test_output_sha_single_is_raw_file_digest(tmp_path: Path) -> None:
    (tmp_path / "out.json").write_text("{}")
    assert hashing.output_sha(tmp_path, ["out.json"]) == hashing.file_sha(tmp_path / "out.json")


def test_output_sha_multi_is_manifest_and_none_when_partial(tmp_path: Path) -> None:
    (tmp_path / "a.tex").write_text("a")
    (tmp_path / "b.dat").write_text("b")
    multi = hashing.output_sha(tmp_path, ["a.tex", "b.dat"])
    assert multi is not None and multi != hashing.file_sha(tmp_path / "a.tex")
    (tmp_path / "b.dat").unlink()
    assert hashing.output_sha(tmp_path, ["a.tex", "b.dat"]) is None


def test_package_sha_tracks_glob_contents(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/a.py").write_text("X = 1")
    before = hashing.package_sha(tmp_path, ["pkg/**/*.py"])
    (tmp_path / "pkg/a.py").write_text("X = 2")
    assert hashing.package_sha(tmp_path, ["pkg/**/*.py"]) != before
    (tmp_path / "pkg/a.py").write_text("X = 1")
    assert hashing.package_sha(tmp_path, ["pkg/**/*.py"]) == before
