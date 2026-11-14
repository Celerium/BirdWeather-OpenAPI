"""Optional checks against the real BirdWeather service (read-only GET requests).

They are skipped unless `BIRDWEATHER_STATION_TOKEN` is set. Never commit a token:

    $env:BIRDWEATHER_STATION_TOKEN = "<station token>"
    $env:BIRDWEATHER_STATION_ID = "<station id>"   # optional, checked against responses
    pytest -m live
"""

from __future__ import annotations

import os
from typing import Any

import pytest
import requests

from birdweather_openapi.builder import build_spec
from birdweather_openapi.constants import SOURCE_URL
from birdweather_openapi.http import fetch_text
from birdweather_openapi.parser import parse_documentation

TOKEN = os.environ.get("BIRDWEATHER_STATION_TOKEN")
STATION_ID = os.environ.get("BIRDWEATHER_STATION_ID")
API = "https://app.birdweather.com/api/v1"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not TOKEN, reason="BIRDWEATHER_STATION_TOKEN is not set"),
]

PYTHON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int, float),  # JSON writers may emit 9.0 for 9
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def type_mismatches(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Documented properties that are present in `value` but have a different type. Null always passes."""
    expected = schema.get("type")
    if value is None or expected is None:
        return []
    if not isinstance(value, PYTHON_TYPES[expected]) or (isinstance(value, bool) and expected != "boolean"):
        return [f"{path}: expected {expected}, got {type(value).__name__}"]
    issues: list[str] = []
    if expected == "object":
        for name, child in schema.get("properties", {}).items():
            if name in value:
                issues += type_mismatches(value[name], child, f"{path}.{name}")
    elif expected == "array":
        for index, item in enumerate(value):
            issues += type_mismatches(item, schema.get("items", {}), f"{path}[{index}]")
    return issues


@pytest.fixture(scope="module")
def spec(snapshot_html):
    return build_spec(parse_documentation(snapshot_html))


def get(path: str, **params: Any) -> dict[str, Any]:
    response = requests.get(f"{API}{path}", params=params, timeout=30)
    assert response.status_code == 200, f"{path}: HTTP {response.status_code}"
    body = response.json()
    assert body.get("success") is True
    return body


def response_schema(spec: dict[str, Any], path: str) -> dict[str, Any]:
    return spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]


@pytest.mark.parametrize(
    ("template", "params", "key"),
    [
        ("/stations/{token}/stats", {}, None),
        ("/stations/{token}/species", {"limit": 1}, "species"),
        ("/stations/{token}/detections", {"limit": 1}, "detections"),
        ("/stations/{token}/soundscapes", {"limit": 1}, "soundscapes"),
    ],
)
def test_station_responses_match_the_generated_spec(spec, template, params, key):
    body = get(template.format(token=TOKEN), **params)
    assert type_mismatches(body, response_schema(spec, template)) == []
    if key:
        assert isinstance(body[key], list)
        if STATION_ID and body[key] and "stationId" in body[key][0]:
            assert str(body[key][0]["stationId"]) == STATION_ID


def test_public_lookups_match_the_generated_spec(spec):
    station = get(f"/stations/{TOKEN}/detections", limit=1)["detections"]
    if not station:
        pytest.skip("station has no detections yet")
    detection_id = station[0]["id"]
    species_id = station[0]["species"]["id"]

    detection = get(f"/detections/{detection_id}")
    assert type_mismatches(detection, response_schema(spec, "/detections/{id}")) == []
    assert detection["detection"]["id"] == detection_id

    species = get(f"/species/{species_id}")
    assert type_mismatches(species, response_schema(spec, "/species/{id}")) == []


def test_live_documentation_still_parses():
    documentation = parse_documentation(fetch_text(SOURCE_URL))
    assert len(documentation.actions) >= 12
    assert documentation.servers[0][1] == API
