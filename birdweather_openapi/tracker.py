"""Fetch the docs, rebuild the spec and only touch the output when the API actually changed."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .builder import build_spec
from .constants import DEFAULT_API_VERSION, SOURCE_URL
from .diff import SpecDiff, comparable, diff_specs, operations, render_markdown
from .http import fetch_text
from .parser import parse_documentation
from .versioning import next_version

log = logging.getLogger("birdweather_openapi")

CHANGELOG_HEADER = f"""\
# Changelog

Every change detected in the [BirdWeather REST API documentation]({SOURCE_URL}) is recorded here,
newest first. Versions are `<API version>.<date of the change>`; see the README for details.
"""
# A drop larger than this is far more likely to be a broken scrape than a real API purge.
MAX_OPERATION_DROP = 0.5


class SuspiciousSpecError(RuntimeError):
    """Raised when the new spec looks like a failed scrape rather than a real API change."""


@dataclass
class UpdateResult:
    changed: bool
    version: str
    previous_version: str | None
    operation_count: int
    diff: SpecDiff
    release_notes: str
    spec: dict[str, Any]


def load_spec(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_spec(spec: dict[str, Any], path: Path) -> None:
    """Atomically write the spec as stable, human-diffable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(serialized)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render_release_notes(operation_count: int, diff: SpecDiff, initial: bool, source_url: str) -> str:
    lines = [f"[BirdWeather API documentation]({source_url})", ""]
    if initial:
        lines.append(f"Initial specification with **{operation_count}** operations.")
    else:
        lines.append(f"**{operation_count}** operations in total — {diff.summary()}.")
        lines += ["", render_markdown(diff)]
    return "\n".join(lines).strip() + "\n"


def update_changelog(path: Path, version: str, today: date, notes: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else CHANGELOG_HEADER
    if f"## {version} " in existing:
        return
    entry = f"## {version} - {today.isoformat()}\n\n{notes.strip()}\n"
    marker = existing.find("\n## ")
    if marker == -1:
        updated = existing.rstrip("\n") + "\n\n" + entry
    else:
        updated = existing[: marker + 1] + entry + "\n" + existing[marker + 1 :]
    path.write_text(updated, encoding="utf-8", newline="\n")


def update_spec(
    output: Path,
    *,
    source_url: str = SOURCE_URL,
    changelog: Path | None = None,
    today: date | None = None,
    fetch: Callable[[str], str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> UpdateResult:
    today = today or datetime.now(timezone.utc).date()
    fetch = fetch or fetch_text
    previous = load_spec(output)
    previous_version = (previous or {}).get("info", {}).get("version")

    documentation = parse_documentation(fetch(source_url))
    candidate = build_spec(documentation, source_url=source_url)
    operation_count = len(operations(candidate))

    if previous is not None:
        if comparable(previous) == comparable(candidate) and not force:
            return UpdateResult(
                False, previous_version or "", previous_version, operation_count, SpecDiff(), "", previous
            )
        previous_count = len(operations(previous))
        if previous_count and operation_count < previous_count * MAX_OPERATION_DROP and not force:
            raise SuspiciousSpecError(
                f"Operation count dropped from {previous_count} to {operation_count}; "
                "refusing to overwrite the spec. Re-run with --force if this is intentional."
            )

    version = next_version(documentation.api_version or DEFAULT_API_VERSION, today, previous_version)
    candidate["info"]["version"] = version
    diff = diff_specs(previous, candidate)
    notes = render_release_notes(operation_count, diff, previous is None, source_url)

    if not dry_run:
        write_spec(candidate, output)
        if changelog is not None:
            update_changelog(changelog, version, today, notes)

    return UpdateResult(True, version, previous_version, operation_count, diff, notes, candidate)
