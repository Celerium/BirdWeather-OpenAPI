"""Shared constants."""

from pathlib import Path

SOURCE_URL = "https://app.birdweather.com/api/v1"
GRAPHQL_DOCS_URL = "https://app.birdweather.com/api/index.html"
REPOSITORY_URL = "https://github.com/Celerium/BirdWeather-OpenAPI"

DEFAULT_OUTPUT = Path("BirdWeather.json")
DEFAULT_CHANGELOG = Path("CHANGELOG.md")

USER_AGENT = f"BirdWeather-OpenAPI-watcher (+{REPOSITORY_URL})"
OPENAPI_VERSION = "3.0.3"
JSON_CONTENT_TYPE = "application/json"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
BINARY_CONTENT_TYPE = "application/octet-stream"

# Used when the documentation page does not list a server.
DEFAULT_SERVER = "https://app.birdweather.com/api/v1"
DEFAULT_API_VERSION = "1"
