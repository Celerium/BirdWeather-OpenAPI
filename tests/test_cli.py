import json

import pytest

from birdweather_openapi import cli


@pytest.fixture()
def served(monkeypatch, mini_html):
    """Serve the saved page instead of calling BirdWeather."""
    monkeypatch.setattr("birdweather_openapi.tracker.fetch_text", lambda url: mini_html)
    return mini_html


def test_cli_writes_then_reports_no_change(tmp_path, served, capsys):
    output = tmp_path / "spec.json"
    args = ["--output", str(output), "--no-changelog"]

    assert cli.main(args) == 0
    assert "Wrote" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["openapi"] == "3.0.3"

    assert cli.main(args) == 0
    assert "No API changes detected" in capsys.readouterr().out


def test_cli_writes_release_notes_and_github_outputs(tmp_path, served):
    notes, outputs = tmp_path / "notes.md", tmp_path / "gh_output"
    args = [
        "--output", str(tmp_path / "spec.json"),
        "--changelog", str(tmp_path / "CHANGELOG.md"),
        "--release-notes-file", str(notes),
        "--github-output", str(outputs),
    ]  # fmt: skip
    assert cli.main(args) == 0
    assert "Initial specification" in notes.read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in outputs.read_text(encoding="utf-8").splitlines())
    assert values["changed"] == "true"
    assert values["tag"] == f"v{values['version']}"

    outputs.unlink()
    assert cli.main(args) == 0
    assert "changed=false" in outputs.read_text(encoding="utf-8")


def test_cli_dry_run_writes_nothing(tmp_path, served, capsys):
    assert cli.main(["--output", str(tmp_path / "spec.json"), "--dry-run"]) == 0
    assert "Would write" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_cli_reports_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("birdweather_openapi.tracker.fetch_text", lambda url: "<html></html>")
    assert cli.main(["--output", str(tmp_path / "spec.json")]) == 1
    assert "ERROR" in capsys.readouterr().err
