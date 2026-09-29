"""Shared pytest fixtures for the Catalog Circulation Planning suite.

The harness restarts the API server before every individual test, so each test
begins against an empty database and builds every precondition it needs
through the documented endpoints.
"""
import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    BROKER,
    DIRECTOR,
    PLANNER,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the service under test."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return ADMIN


@pytest.fixture
def circulation_planner_headers() -> dict:
    return PLANNER


@pytest.fixture
def circulation_director_headers() -> dict:
    return DIRECTOR


@pytest.fixture
def list_broker_headers() -> dict:
    return BROKER


@pytest.fixture
def marketing_analyst_headers() -> dict:
    return ANALYST
