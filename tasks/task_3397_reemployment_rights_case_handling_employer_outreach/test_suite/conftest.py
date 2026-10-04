"""Pytest fixtures exposing the test_helpers infrastructure.

The harness restarts the API server before every test, so each test starts
against an empty database and builds the world it needs through the public
API. The base URL is injected into the environment by the runner, so the
client is constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    AGENCY_REVIEWER_HEADERS,
    ANONYMOUS_HEADERS,
    COORDINATOR_ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    COORDINATOR_LEAD_HEADERS,
    make_agency_reviewer_headers,
    make_coordinator_headers,
    make_employer_headers,
    make_ombudsman_headers,
    make_service_member_headers,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test (fresh deployment per test)."""
    return ApiClient()


# ── Opaque-role header fixtures ────────────────────────────────────────────

@pytest.fixture()
def anonymous_headers() -> dict:
    """Unauthenticated registrant: no X-User-ID at all."""
    return ANONYMOUS_HEADERS


@pytest.fixture()
def coordinator_headers() -> dict:
    return COORDINATOR_HEADERS


@pytest.fixture()
def coordinator_admin_headers() -> dict:
    """The standing proctor identity used by the certification fixture."""
    return COORDINATOR_ADMIN_HEADERS


@pytest.fixture()
def coordinator_lead_headers() -> dict:
    """The standing certifier identity (never a proctor of fixture records)."""
    return COORDINATOR_LEAD_HEADERS


@pytest.fixture()
def agency_reviewer_headers() -> dict:
    return AGENCY_REVIEWER_HEADERS


# ── Entity-backed header builders ──────────────────────────────────────────
# These roles are ownership-checked against a stored entity id, so the fixture
# hands the test the builder; call it with the entity the test created.

@pytest.fixture()
def member_headers():
    """make_service_member_headers(member_id) for the acting member."""
    return make_service_member_headers


@pytest.fixture()
def employer_headers():
    """make_employer_headers(employer_id) for the acting employer."""
    return make_employer_headers


@pytest.fixture()
def ombudsman_headers():
    """make_ombudsman_headers(ombudsman_id) for the acting ombudsman."""
    return make_ombudsman_headers


@pytest.fixture()
def coordinator_headers_for():
    """make_coordinator_headers(user_id) for an arbitrary coordinator id."""
    return make_coordinator_headers


@pytest.fixture()
def agency_headers_for():
    """make_agency_reviewer_headers(user_id) for an arbitrary agency reviewer."""
    return make_agency_reviewer_headers


# ── Composite world ────────────────────────────────────────────────────────

@pytest.fixture()
def world(api: ApiClient) -> dict:
    """Clock set to the program default plus one employer, one member and one
    certified ombudsman - the standing arrangement most tests build on."""
    return fx.setup_basic_world(api)
