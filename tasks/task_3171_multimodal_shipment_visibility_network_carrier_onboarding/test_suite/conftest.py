"""Shared pytest wiring for the Multimodal Shipment Visibility suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API. The base URL is injected into the environment by the runner, so the
client is constructed with no arguments.
"""

import pytest

from test_helpers import (
    CUSTOMER_SERVICE_HEADERS,
    NETWORK_OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    ApiClient,
    fixtures,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def platform_admin_headers():
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture()
def network_ops_headers():
    return NETWORK_OPS_HEADERS


@pytest.fixture()
def customer_service_headers():
    return CUSTOMER_SERVICE_HEADERS
