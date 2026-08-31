"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def ce_manager_headers():
    return TEST_USERS["ce_manager_headers"]


@pytest.fixture
def biomed_tech_headers():
    return TEST_USERS["biomed_tech_headers"]


@pytest.fixture
def biomed_tech_peer_headers():
    return TEST_USERS["biomed_tech_peer_headers"]


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def dept_steward_headers():
    return TEST_USERS["dept_steward_headers"]


@pytest.fixture
def vendor_rep_headers():
    return TEST_USERS["vendor_rep_headers"]
