"""Pytest fixtures exposing the Drone Operations Service test helpers.

The runner owns the server lifecycle and injects `API_BASE_URL`, so the client is
built once per session and never health-checks the process itself. Every data
fixture is function-scoped because the harness restarts the service — and so
empties the datastore — before each individual test.
"""

import pytest

from test_helpers import (
    AIRSPACE_AUTHORITY,
    AIRSPACE_AUTHORITY_2,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_2,
    INVESTIGATION_OFFICER,
    INVESTIGATION_OFFICER_2,
    SAFETY_REVIEWER,
    SAFETY_REVIEWER_2,
    WAIVER_APPROVER,
    WAIVER_APPROVER_2,
    ApiClient,
    Clock,
    make_pilot_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointed at the service under test."""
    return ApiClient()


@pytest.fixture
def clock(api) -> Clock:
    """A tracker for the service's logical clock, starting at its startup value.

    The service exposes no clock-read endpoint, so the value is mirrored locally
    and every advance goes through the clock endpoint.
    """
    return Clock(api)


@pytest.fixture
def compliance_officer():
    return COMPLIANCE_OFFICER


@pytest.fixture
def compliance_officer_2():
    return COMPLIANCE_OFFICER_2


@pytest.fixture
def airspace_authority():
    return AIRSPACE_AUTHORITY


@pytest.fixture
def airspace_authority_2():
    return AIRSPACE_AUTHORITY_2


@pytest.fixture
def safety_reviewer():
    return SAFETY_REVIEWER


@pytest.fixture
def safety_reviewer_2():
    return SAFETY_REVIEWER_2


@pytest.fixture
def waiver_approver():
    return WAIVER_APPROVER


@pytest.fixture
def waiver_approver_2():
    return WAIVER_APPROVER_2


@pytest.fixture
def investigation_officer():
    return INVESTIGATION_OFFICER


@pytest.fixture
def investigation_officer_2():
    return INVESTIGATION_OFFICER_2


@pytest.fixture
def pilot_headers():
    """Builder for the entity-backed Pilot role.

    `X-User-ID` must be the acting pilot's own `id`, so tests receive the builder
    rather than a fixed header dict.
    """
    return make_pilot_headers
