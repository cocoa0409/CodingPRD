"""Pytest fixtures exposing the board's test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def board_admin_headers():
    return TEST_USERS["board_admin_headers"]


@pytest.fixture
def licensing_analyst_headers():
    return TEST_USERS["licensing_analyst_headers"]


@pytest.fixture
def hearing_clerk_headers():
    return TEST_USERS["hearing_clerk_headers"]


@pytest.fixture
def complaint_investigator_headers():
    return TEST_USERS["complaint_investigator_headers"]


@pytest.fixture
def dealer_headers():
    """Shared Dealer headers. Ownership-gated calls must instead use
    make_dealer_headers(dealer["id"])."""
    return TEST_USERS["dealer_headers"]


@pytest.fixture
def manufacturer_headers():
    """Shared Manufacturer headers. Ownership-gated calls must instead use
    make_manufacturer_headers(manufacturer["id"])."""
    return TEST_USERS["manufacturer_headers"]
