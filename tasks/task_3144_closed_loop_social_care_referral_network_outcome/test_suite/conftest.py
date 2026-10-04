"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every test, so every test starts
against an empty database and builds its own preconditions.
"""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_case_worker_headers, make_org_admin_headers, make_funder_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def case_worker_headers():
    return TEST_USERS["case_worker_headers"]


@pytest.fixture
def org_admin_headers():
    return TEST_USERS["org_admin_headers"]


@pytest.fixture
def funder_admin_headers():
    return TEST_USERS["funder_admin_headers"]


@pytest.fixture
def case_worker_header_builder():
    return make_case_worker_headers


@pytest.fixture
def org_admin_header_builder():
    return make_org_admin_headers


@pytest.fixture
def funder_admin_header_builder():
    return make_funder_admin_headers
