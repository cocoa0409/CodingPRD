"""Pytest fixtures exposing the test_helpers infrastructure.

The harness restarts the API against an empty database before every test, so
no fixture here caches domain state: only the HTTP client and the per-role
header dictionaries are shared.
"""

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_advisor_headers,
    make_coordinator_headers,
    make_director_headers,
    make_tech_headers,
    make_vet_headers,
)
from test_helpers.test_users import (
    ADVISOR_ALT_USER_ID,
    COORDINATOR_ALT_USER_ID,
    DIRECTOR_ALT_USER_ID,
    TECH_ALT_USER_ID,
    TECH_THIRD_USER_ID,
    VET_ALT_USER_ID,
    VET_THIRD_USER_ID,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the harness."""
    return api_client


@pytest.fixture
def director():
    return make_director_headers()


@pytest.fixture
def director_alt():
    return make_director_headers(DIRECTOR_ALT_USER_ID)


@pytest.fixture
def vet():
    return make_vet_headers()


@pytest.fixture
def vet_alt():
    return make_vet_headers(VET_ALT_USER_ID)


@pytest.fixture
def vet_third():
    return make_vet_headers(VET_THIRD_USER_ID)


@pytest.fixture
def tech():
    return make_tech_headers()


@pytest.fixture
def tech_alt():
    return make_tech_headers(TECH_ALT_USER_ID)


@pytest.fixture
def tech_third():
    return make_tech_headers(TECH_THIRD_USER_ID)


@pytest.fixture
def coordinator():
    return make_coordinator_headers()


@pytest.fixture
def coordinator_alt():
    return make_coordinator_headers(COORDINATOR_ALT_USER_ID)


@pytest.fixture
def advisor():
    return make_advisor_headers()


@pytest.fixture
def advisor_alt():
    return make_advisor_headers(ADVISOR_ALT_USER_ID)
