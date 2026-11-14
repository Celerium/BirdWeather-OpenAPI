from pathlib import Path

import pytest

from birdweather_openapi.builder import build_spec
from birdweather_openapi.parser import parse_documentation

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def mini_html() -> str:
    return (FIXTURES / "mini.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def snapshot_html() -> str:
    """A saved copy of https://app.birdweather.com/api/v1 (scripts and styles removed)."""
    return (FIXTURES / "birdweather_v1_snapshot.html").read_text(encoding="utf-8")


@pytest.fixture()
def mini_doc(mini_html):
    return parse_documentation(mini_html)


@pytest.fixture()
def mini_spec(mini_doc):
    return build_spec(mini_doc, version="2.20260101")
