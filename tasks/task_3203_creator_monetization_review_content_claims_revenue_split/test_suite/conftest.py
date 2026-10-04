"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop, empty database per test) is owned by
prd-bench-local-runner; this file only wires up holders.
"""
import pytest

from test_helpers import TEST_USERS, api_client, ApiClient


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def creator_headers():
    return TEST_USERS["creator_headers"]


@pytest.fixture
def rights_holder_headers():
    return TEST_USERS["rights_holder_headers"]


@pytest.fixture
def moderator_headers():
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def monetization_reviewer_headers():
    return TEST_USERS["monetization_reviewer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]