"""Shared pytest fixtures for the Film Sales Presale API suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    api_client,
    make_buyer_headers,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client, pointed at the base URL the runner supplies."""
    return api_client


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]


@pytest.fixture
def head_of_sales_headers():
    return TEST_USERS["head_of_sales_headers"]


@pytest.fixture
def delivery_manager_headers():
    return TEST_USERS["delivery_manager_headers"]


@pytest.fixture
def collection_agent_headers():
    return TEST_USERS["collection_agent_headers"]


@pytest.fixture
def lender_headers():
    return TEST_USERS["lender_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def buyer_headers_unowned():
    """A Buyer role header pair whose identity is not any real Buyer row."""
    return TEST_USERS["buyer_headers_unowned"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]


@pytest.fixture
def buyer_headers_factory():
    """Build Buyer headers for a specific Buyer row, since Buyer identity is the
    id of the acting Buyer entity."""
    return make_buyer_headers
