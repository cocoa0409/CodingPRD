"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is managed externally: the harness restarts the API
server before every test, so each test begins against an empty database and
the default logical-clock reading. Tests import domain helpers straight from
test_helpers; these fixtures exist for the client and the role headers.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is already running."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def placement_officer_headers():
    return TEST_USERS["placement_officer_headers"]


@pytest.fixture
def medical_officer_headers():
    return TEST_USERS["medical_officer_headers"]


@pytest.fixture
def legal_reviewer_headers():
    return TEST_USERS["legal_reviewer_headers"]


@pytest.fixture
def legal_reviewer_background_headers():
    return TEST_USERS["legal_reviewer_background_headers"]


@pytest.fixture
def legal_reviewer_suitability_headers():
    return TEST_USERS["legal_reviewer_suitability_headers"]


@pytest.fixture
def training_director_headers():
    return TEST_USERS["training_director_headers"]


@pytest.fixture
def country_director_headers():
    return TEST_USERS["country_director_headers"]
