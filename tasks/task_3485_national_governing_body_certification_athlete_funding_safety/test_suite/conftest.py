"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and restarts the API server before
every test, so each test starts against an empty database and the startup
logical clock (2026-09-01T00:00:00Z). The autouse fixture below resets the
helpers' clock tracker to match that guarantee.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_athlete_headers,
    make_ngb_admin_headers,
    reset_clock_tracker,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_clock_tracker():
    """The server restarts per test with the startup clock; keep the
    helpers' tracker in sync."""
    reset_clock_tracker()
    yield


# ---------------------------------------------------------------------------
# Role header fixtures (opaque roles — shared constants are canonical)
# ---------------------------------------------------------------------------

@pytest.fixture
def committee_admin_headers():
    return TEST_USERS["committee_admin_headers"]


@pytest.fixture
def committee_admin_alt_headers():
    return TEST_USERS["committee_admin_alt_headers"]


@pytest.fixture
def interim_manager_headers():
    return TEST_USERS["interim_manager_headers"]


@pytest.fixture
def auditor_issuer_headers():
    return TEST_USERS["auditor_issuer_headers"]


@pytest.fixture
def auditor_closer_headers():
    return TEST_USERS["auditor_closer_headers"]


@pytest.fixture
def auditor_third_headers():
    return TEST_USERS["auditor_third_headers"]


@pytest.fixture
def safe_sport_officer_headers():
    return TEST_USERS["safe_sport_officer_headers"]


@pytest.fixture
def safe_sport_officer_alt_headers():
    return TEST_USERS["safe_sport_officer_alt_headers"]


@pytest.fixture
def arbitrator_headers():
    return TEST_USERS["arbitrator_headers"]


@pytest.fixture
def arbitrator_alt_headers():
    return TEST_USERS["arbitrator_alt_headers"]


@pytest.fixture
def results_official_headers():
    return TEST_USERS["results_official_headers"]


@pytest.fixture
def results_official_alt_headers():
    return TEST_USERS["results_official_alt_headers"]


# ---------------------------------------------------------------------------
# Entity-backed roles — shared constants are FALLBACKS for non-ownership
# tests only; ownership-gated calls must build headers from the real entity
# id via the builders below.
# ---------------------------------------------------------------------------

@pytest.fixture
def ngb_admin_headers():
    return TEST_USERS["ngb_admin_headers"]


@pytest.fixture
def athlete_headers():
    return TEST_USERS["athlete_headers"]


@pytest.fixture
def ngb_admin_headers_for():
    """Builder fixture: ngb_admin_headers_for(body_id) -> ownership-correct
    NGBAdmin headers for that governing body."""
    return make_ngb_admin_headers


@pytest.fixture
def athlete_headers_for():
    """Builder fixture: athlete_headers_for(athlete_id) -> ownership-correct
    Athlete headers for that athlete."""
    return make_athlete_headers
