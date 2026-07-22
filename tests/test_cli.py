from pathlib import Path

from federalgraph.cli import main


def test_doctor_command(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sources.json").write_text('{"sources": {}}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(["doctor"])

    assert result == 0
    assert '"config_exists": true' in capsys.readouterr().out
