"""
Shared fixtures for the County Veterans Service Office API suite.

The server is restarted before every test, so each test starts against an
empty database and builds every precondition it needs through the API.
"""

import pytest
from test_helpers import (
    INTAKE_CLERK_HEADERS,
    STATE_AUDITOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    TEST_USERS,
    UNKNOWN_COUNTY_OFFICER_HEADERS,
    UNKNOWN_VETERAN_CLIENT_HEADERS,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    """The endpoint client, shared for the whole session."""
    return api_client


@pytest.fixture
def system_admin():
    """The configuration operator, whose identifier is opaque."""
    return dict(SYSTEM_ADMIN_HEADERS)


@pytest.fixture
def intake_clerk():
    """The front-counter operator, whose identifier is opaque."""
    return dict(INTAKE_CLERK_HEADERS)


@pytest.fixture
def state_auditor():
    """The oversight operator, whose identifier is opaque."""
    return dict(STATE_AUDITOR_HEADERS)


@pytest.fixture
def unknown_county_officer():
    """A county officer header pair whose identifier resolves to no roster row."""
    return dict(UNKNOWN_COUNTY_OFFICER_HEADERS)


@pytest.fixture
def unknown_veteran_client():
    """A veteran client header pair whose identifier resolves to no intake row."""
    return dict(UNKNOWN_VETERAN_CLIENT_HEADERS)


@pytest.fixture
def test_users():
    """The five role identities, keyed by role."""
    return dict(TEST_USERS)
