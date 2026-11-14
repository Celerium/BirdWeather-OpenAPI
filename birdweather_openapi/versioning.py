"""BirdWeather publishes no changelog, so spec versions are `<api major>.<change date>`."""

from __future__ import annotations

import re
from datetime import date

REVISION_PATTERN = re.compile(r"^(?P<base>.+\.\d{8})(?:\.(?P<revision>\d+))?$")


def next_version(api_version: str, today: date, previous_version: str | None = None) -> str:
    """Pick the version for a spec that is known to have changed.

    * First change on a given day     -> `1.20261114`
    * Another change on the same day  -> a numeric revision is appended (`1.20261114.2`).
    """
    candidate = f"{api_version}.{today:%Y%m%d}"
    if previous_version:
        match = REVISION_PATTERN.match(previous_version)
        previous_base = match.group("base") if match else previous_version
        if candidate == previous_base:
            revision = int(match.group("revision") or 1) if match else 1
            return f"{candidate}.{revision + 1}"
    return candidate
