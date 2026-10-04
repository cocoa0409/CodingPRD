"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle (the API is restarted before every test, so
every test begins against an empty database) and PYTHONPATH.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def fulfillment_headers():
    return TEST_USERS["fulfillment_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def marketing_headers():
    return TEST_USERS["marketing_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]