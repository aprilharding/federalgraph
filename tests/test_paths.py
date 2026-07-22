from pathlib import Path

from federalgraph.paths import ProjectPaths


def test_discover_project_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    paths = ProjectPaths.discover(nested)

    assert paths.root == tmp_path
    assert paths.processed == tmp_path / "data" / "processed"
