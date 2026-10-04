"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; the client
reads it from the environment.
"""

import pytest

from test_helpers.api_client import api_client, ApiClient
from test_helpers.test_users import (
    auditor_headers,
    hr_closer_headers,
    hr_poster_headers,
    planner_headers,
    real_estate_headers,
    scd_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def scd():
    return scd_headers()


@pytest.fixture
def planner():
    return planner_headers()


@pytest.fixture
def auditor():
    return auditor_headers()


@pytest.fixture
def real_estate():
    return real_estate_headers()


@pytest.fixture
def hr_poster():
    return hr_poster_headers()


@pytest.fixture
def hr_closer():
    return hr_closer_headers()
