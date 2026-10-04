"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every test, so each test begins
against an empty database and builds whatever state it needs through the
public API. The base URL comes from the environment, injected by the runner.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def veterinary_staff_headers():
    return TEST_USERS["veterinary_staff_headers"]


@pytest.fixture
def grooming_staff_headers():
    return TEST_USERS["grooming_staff_headers"]


@pytest.fixture
def vaccination_staff_headers():
    return TEST_USERS["vaccination_staff_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def pharmacy_staff_headers():
    return TEST_USERS["pharmacy_staff_headers"]


@pytest.fixture
def training_staff_headers():
    return TEST_USERS["training_staff_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]