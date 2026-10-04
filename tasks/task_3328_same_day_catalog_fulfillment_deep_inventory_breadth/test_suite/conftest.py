"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH and API_BASE_URL; the server is restarted before every
individual test, so the database is empty at the start of each one.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
)
from test_helpers import TEST_USERS, make_customer_account_headers


@pytest.fixture(scope="session")
def api():
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def catalog_curator_headers():
    return TEST_USERS["catalog_curator_headers"]


@pytest.fixture
def warehouse_picker_headers():
    return TEST_USERS["warehouse_picker_headers"]


@pytest.fixture
def dc_manager_headers():
    return TEST_USERS["dc_manager_headers"]


@pytest.fixture
def errors():
    return ApiErrorId


@pytest.fixture
def as_account():
    """Build ownership-gated headers for a specific account id."""
    return make_customer_account_headers