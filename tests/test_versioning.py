from datetime import date

import pytest

from birdweather_openapi.versioning import next_version

TODAY = date(2026, 11, 14)


def test_first_version_uses_the_date():
    assert next_version("1", TODAY) == "1.20261114"


def test_new_day_gets_a_new_version():
    assert next_version("1", TODAY, "1.20261113") == "1.20261114"
    assert next_version("1", TODAY, "1.20261113.4") == "1.20261114"


@pytest.mark.parametrize(
    ("previous", "expected"),
    [("1.20261114", "1.20261114.2"), ("1.20261114.2", "1.20261114.3")],
)
def test_same_day_change_gets_a_revision(previous, expected):
    assert next_version("1", TODAY, previous) == expected


def test_new_api_major_resets_the_version():
    assert next_version("2", TODAY, "1.20261114") == "2.20261114"
