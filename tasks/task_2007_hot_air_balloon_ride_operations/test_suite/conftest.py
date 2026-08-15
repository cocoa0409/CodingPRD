"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def chase_headers():
    return TEST_USERS["chase_headers"]


@pytest.fixture
def anon_headers():
    return TEST_USERS["anon_headers"]


@pytest.fixture
def pilot_headers():
    """Shared Pilot headers — only for calls that are not pilot-scoped.
    For pilot-scoped calls use make_pilot_headers(pilot["id"])."""
    return TEST_USERS["pilot_headers"]


@pytest.fixture
def customer_headers():
    """Shared Customer headers — only for calls that are not ownership-gated.
    For ownership-gated calls use make_customer_headers(customer["id"])."""
    return TEST_USERS["customer_headers"]
