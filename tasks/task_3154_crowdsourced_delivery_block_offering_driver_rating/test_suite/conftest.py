"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def station_ops_headers():
    return TEST_USERS["station_ops_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["appeals_reviewer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def driver_headers():
    # Shared constant for the entity_backed Driver role: only safe for tests
    # that do not exercise ownership. Ownership-gated calls must use
    # make_driver_headers(<driver_id>) instead.
    return TEST_USERS["driver_headers"]
