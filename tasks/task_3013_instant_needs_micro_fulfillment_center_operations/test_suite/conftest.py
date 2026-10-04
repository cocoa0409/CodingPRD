"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, SITE_OPS_HEADERS, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def site_ops_headers():
    """A SiteOps caller; its X-User-ID is opaque and never looked up."""
    return SITE_OPS_HEADERS


@pytest.fixture
def unknown_customer_headers():
    """A Customer caller whose X-User-ID matches no existing customer row."""
    return TEST_USERS["unknown_customer_headers"]


@pytest.fixture
def unknown_picker_headers():
    """A Picker caller whose X-User-ID matches no existing picker row."""
    return TEST_USERS["unknown_picker_headers"]


@pytest.fixture
def unknown_driver_headers():
    """A Driver caller whose X-User-ID matches no existing driver row."""
    return TEST_USERS["unknown_driver_headers"]
