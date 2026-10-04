"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests import domain helpers
from test_helpers directly and take the session-scoped API client from here.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def product_lead_headers() -> dict:
    return TEST_USERS["product_lead_headers"]


@pytest.fixture
def sourcing_manager_headers() -> dict:
    return TEST_USERS["sourcing_manager_headers"]


@pytest.fixture
def claims_scientist_headers() -> dict:
    return TEST_USERS["claims_scientist_headers"]


@pytest.fixture
def claims_scientist_alt_headers() -> dict:
    return TEST_USERS["claims_scientist_alt_headers"]


@pytest.fixture
def media_buyer_headers() -> dict:
    return TEST_USERS["media_buyer_headers"]


@pytest.fixture
def retail_exec_headers() -> dict:
    return TEST_USERS["retail_exec_headers"]


@pytest.fixture
def legal_counsel_headers() -> dict:
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def legal_counsel_alt_headers() -> dict:
    return TEST_USERS["legal_counsel_alt_headers"]
