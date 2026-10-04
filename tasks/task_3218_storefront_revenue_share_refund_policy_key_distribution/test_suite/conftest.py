"""Pytest fixtures exposing test_helpers infrastructure.

The server's lifecycle (start, readiness, restart before each test) is owned by
prd-bench-local-runner; this module only wires the client and the role headers
into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_ops_headers():
    return TEST_USERS["platform_ops_headers"]


@pytest.fixture
def store_reviewer_headers():
    return TEST_USERS["store_reviewer_headers"]


@pytest.fixture
def trust_safety_headers():
    return TEST_USERS["trust_safety_headers"]


@pytest.fixture
def developer_headers():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def user_headers():
    return TEST_USERS["user_headers"]
