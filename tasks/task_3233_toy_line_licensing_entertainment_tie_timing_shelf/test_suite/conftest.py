"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the API server before each test, so every test begins
against an empty database and builds its own world through the public API.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture()
def admin_headers():
    return TEST_USERS["platform_admin"]


@pytest.fixture()
def brand_manager_headers():
    return TEST_USERS["brand_manager"]


@pytest.fixture()
def studio_rep_headers():
    return TEST_USERS["studio_rep"]


@pytest.fixture()
def retailer_ops_headers():
    return TEST_USERS["retailer_ops"]


@pytest.fixture()
def safety_engineer_headers():
    return TEST_USERS["safety_engineer"]
