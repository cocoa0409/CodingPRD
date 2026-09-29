"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def center_admin_headers():
    return TEST_USERS["center_admin_headers"]


@pytest.fixture
def access_coordinator_headers():
    return TEST_USERS["access_coordinator_headers"]


@pytest.fixture
def facility_coordinator_headers():
    return TEST_USERS["facility_coordinator_headers"]


@pytest.fixture
def interventionalist_headers():
    return TEST_USERS["interventionalist_headers"]


@pytest.fixture
def sedation_rn_headers():
    return TEST_USERS["sedation_rn_headers"]


@pytest.fixture
def coder_headers():
    return TEST_USERS["coder_headers"]
