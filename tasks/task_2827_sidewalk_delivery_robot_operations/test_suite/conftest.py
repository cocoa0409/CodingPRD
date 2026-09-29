"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers import NO_AUTH_HEADERS as _NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    """The municipal-compliance and configuration authority."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def fleet_dispatcher_headers() -> dict:
    """Runs the fleet: dispatch, planning, depot reservations, duty."""
    return TEST_USERS["fleet_dispatcher_headers"]


@pytest.fixture
def fleet_dispatcher_2_headers() -> dict:
    """A second dispatcher identity."""
    return TEST_USERS["fleet_dispatcher_2_headers"]


@pytest.fixture
def remote_operator_headers() -> dict:
    """Occupies the teleoperation seat."""
    return TEST_USERS["remote_operator_headers"]


@pytest.fixture
def remote_operator_2_headers() -> dict:
    """A second teleoperator, for the takeover-control checks."""
    return TEST_USERS["remote_operator_2_headers"]


@pytest.fixture
def safety_officer_headers() -> dict:
    """Owns robot health and the municipal reporting workflow."""
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def safety_officer_2_headers() -> dict:
    """A second officer, for separation of duties on incident submission."""
    return TEST_USERS["safety_officer_2_headers"]


@pytest.fixture
def safety_officer_3_headers() -> dict:
    """A third officer, neither filer nor reviewer of a report."""
    return TEST_USERS["safety_officer_3_headers"]


@pytest.fixture
def customer_support_headers() -> dict:
    """Faces the customer after a failed or late delivery."""
    return TEST_USERS["customer_support_headers"]


@pytest.fixture
def merchant_operator_headers() -> dict:
    """Fallback merchant identity. Ownership-gated calls must instead build
    headers from the merchant row they act for."""
    return TEST_USERS["merchant_operator_headers"]


@pytest.fixture
def no_auth_headers() -> dict:
    """Headers carrying neither X-User-ID nor X-User-Role."""
    return dict(_NO_AUTH_HEADERS)
