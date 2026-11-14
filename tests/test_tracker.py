import json
from datetime import date

import pytest

from birdweather_openapi.tracker import SuspiciousSpecError, update_changelog, update_spec

URL = "https://example.test/doc"
DAY1, DAY2 = date(2026, 1, 1), date(2026, 1, 2)


def run(output, html, today=DAY1, **kwargs):
    return update_spec(output, source_url=URL, fetch=lambda url: html, today=today, **kwargs)


def test_first_run_writes_spec_and_changelog(tmp_path, mini_html):
    output, changelog = tmp_path / "spec.json", tmp_path / "CHANGELOG.md"
    result = run(output, mini_html, changelog=changelog)

    assert result.changed and result.previous_version is None
    assert result.version == "2.20260101"
    spec = json.loads(output.read_text(encoding="utf-8"))
    assert spec["info"]["version"] == "2.20260101"
    assert len(spec["paths"]) == 4
    text = changelog.read_text(encoding="utf-8")
    assert "## 2.20260101 - 2026-01-01" in text and "Initial specification with **5** operations" in text


def test_unchanged_documentation_does_not_touch_the_files(tmp_path, mini_html):
    output, changelog = tmp_path / "spec.json", tmp_path / "CHANGELOG.md"
    run(output, mini_html, changelog=changelog)
    spec_before, log_before = output.read_bytes(), changelog.read_bytes()
    mtime = output.stat().st_mtime_ns

    result = run(output, mini_html, today=DAY2, changelog=changelog)

    assert not result.changed and result.version == "2.20260101"
    assert output.read_bytes() == spec_before and changelog.read_bytes() == log_before
    assert output.stat().st_mtime_ns == mtime


def test_changed_documentation_updates_spec_and_changelog(tmp_path, mini_html):
    output, changelog = tmp_path / "spec.json", tmp_path / "CHANGELOG.md"
    run(output, mini_html, changelog=changelog)

    changed = mini_html.replace("Maximum number of birds", "Maximum number of birds returned")
    result = run(output, changed, today=DAY2, changelog=changelog)

    assert result.changed and result.version == "2.20260102"
    assert result.previous_version == "2.20260101"
    assert result.diff.changed == {
        "GET /stations/{token}/birds": ["parameter `limit` (query): description changed"]
    }
    text = changelog.read_text(encoding="utf-8")
    assert text.index("## 2.20260102") < text.index("## 2.20260101")


def test_second_change_on_the_same_day_gets_a_revision(tmp_path, mini_html):
    output = tmp_path / "spec.json"
    run(output, mini_html)
    result = run(output, mini_html.replace("Adds a bird.", "Adds one bird."))
    assert result.version == "2.20260101.2"


def test_dry_run_writes_nothing(tmp_path, mini_html):
    output, changelog = tmp_path / "spec.json", tmp_path / "CHANGELOG.md"
    result = run(output, mini_html, changelog=changelog, dry_run=True)
    assert result.changed
    assert not output.exists() and not changelog.exists()


def test_force_rewrites_even_without_changes(tmp_path, mini_html):
    output = tmp_path / "spec.json"
    run(output, mini_html)
    result = run(output, mini_html, today=DAY2, force=True)
    assert result.changed and result.version == "2.20260102"


def test_broken_scrape_is_refused(tmp_path, mini_html):
    output = tmp_path / "spec.json"
    run(output, mini_html)
    before = output.read_bytes()
    head = mini_html.split('<div id="birds-birds-post"')[0]
    one_endpoint = head + "</div></section></div></div></body></html>"

    with pytest.raises(SuspiciousSpecError):
        run(output, one_endpoint, today=DAY2)
    assert output.read_bytes() == before


def test_page_without_endpoints_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="No resource groups"):
        run(tmp_path / "spec.json", "<html><body>Down for maintenance</body></html>")
    assert not (tmp_path / "spec.json").exists()


def test_changelog_entry_is_not_duplicated(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    update_changelog(changelog, "1.20260101", DAY1, "notes")
    update_changelog(changelog, "1.20260101", DAY1, "notes")
    assert changelog.read_text(encoding="utf-8").count("## 1.20260101 ") == 1
