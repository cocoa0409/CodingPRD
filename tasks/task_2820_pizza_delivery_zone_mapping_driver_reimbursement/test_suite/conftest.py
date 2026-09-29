"""Pytest fixtures exposing the shared test_helpers infrastructure.

The server lifecycle belongs to prd-bench-local-runner: it restarts the service
before every test, so each test opens against an empty database and builds all of
its own state through the documented endpoints.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def store_manager_headers():
    """A store-manager identity whose X-User-ID is not yet any store's identifier."""
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def driver_headers():
    """A driver identity whose X-User-ID is not yet any driver's identifier."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def dispatcher_headers():
    """A dispatcher identity. Dispatcher identities are opaque."""
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def compliance_officer_headers():
    """A compliance-officer identity. Officer identities are opaque."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def customer_care_headers():
    """A customer-care-agent identity. Agent identities are opaque."""
    return TEST_USERS["customer_care_headers"]
