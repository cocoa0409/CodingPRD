"""Pytest wiring for the Cosmetology Board Compliance suite.

The runner wipes the database and relaunches the server before every test, so
the logical clock is back at ``2026-08-01T00:00:00Z`` for each one and no test
may depend on state another test left behind.
"""
import pytest

# Importing the barrel registers the error_id to HTTP status map and pulls in
# every fixture defined in test_helpers.fixtures.
from test_helpers import ApiClient, api_client  # noqa: F401
from test_helpers.fixtures import (  # noqa: F401
    api,
    critical_code,
    establishment,
    hazard_code,
    licensed_practitioner,
    major_code,
    minor_code,
    posted_salon,
)
from test_helpers.test_users import (
    BOARD_ADMIN_HEADERS,
    HEALTH_LIAISON_HEADERS,
    HEARING_OFFICER_HEADERS,
    INSPECTOR_HEADERS,
)


@pytest.fixture
def admin_headers():
    return BOARD_ADMIN_HEADERS


@pytest.fixture
def inspector_headers():
    return INSPECTOR_HEADERS


@pytest.fixture
def officer_headers():
    return HEARING_OFFICER_HEADERS


@pytest.fixture
def liaison_headers():
    return HEALTH_LIAISON_HEADERS
