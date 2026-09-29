"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client
from test_helpers import fixtures as fx


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def ed_physician_headers():
    return TEST_USERS["ed_physician_headers"]


@pytest.fixture
def ed_physician_alt_headers():
    return TEST_USERS["ed_physician_alt_headers"]


@pytest.fixture
def transfer_coordinator_headers():
    return TEST_USERS["transfer_coordinator_headers"]


@pytest.fixture
def quality_abstractor_headers():
    return TEST_USERS["quality_abstractor_headers"]


@pytest.fixture
def quality_attester_headers():
    return TEST_USERS["quality_attester_headers"]


@pytest.fixture
def program_coordinator_headers():
    return TEST_USERS["program_coordinator_headers"]


@pytest.fixture
def program_coordinator_alt_headers():
    return TEST_USERS["program_coordinator_alt_headers"]


@pytest.fixture
def certification_reviewer_headers():
    return TEST_USERS["certification_reviewer_headers"]


@pytest.fixture
def certification_reviewer_alt_headers():
    return TEST_USERS["certification_reviewer_alt_headers"]


@pytest.fixture
def neurologist_headers():
    """Placeholder Neurologist identity - never use on an ownership-gated call."""
    return TEST_USERS["neurologist_headers"]


@pytest.fixture
def base_clock() -> str:
    """Drive the logical clock to the suite's base day and hand back the instant."""
    fx.set_clock(fx.BASE_DAY)
    return fx.BASE_DAY


@pytest.fixture
def network() -> dict:
    """A hub, a spoke, an ACTIVE agreement and one credentialed on-call neurologist."""
    return fx.setup_network()
