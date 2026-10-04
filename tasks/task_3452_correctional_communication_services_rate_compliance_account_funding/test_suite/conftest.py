"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection, and PYTHONPATH —
tests assume the server is already running and reachable. The logical clock
is pinned to the PRD §2.4 default (2026-09-01T00:00:00Z) before every test
so clock-derived assertions are deterministic regardless of execution order
(the clock endpoint is PlatformAdmin-only and mounted outside the API
prefix; test_helpers.set_clock handles the path).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    CLOCK_DEFAULT_UTC,
    api_client,
    set_clock,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture(autouse=True)
def _logical_clock_default():
    """Pin the server logical clock to the PRD §2.4 default before each test."""
    set_clock(CLOCK_DEFAULT_UTC)
    yield


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def state_regulator_headers():
    return TEST_USERS["state_regulator_headers"]


@pytest.fixture
def facility_staff_headers():
    return TEST_USERS["facility_staff_headers"]


@pytest.fixture
def facility_staff_alt_headers():
    return TEST_USERS["facility_staff_alt_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]


@pytest.fixture
def recipient_party_headers():
    return TEST_USERS["recipient_party_headers"]
