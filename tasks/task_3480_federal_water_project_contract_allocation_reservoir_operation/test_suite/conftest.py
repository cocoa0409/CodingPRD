"""Shared pytest wiring for the Federal Water Allocation suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API (see ``test_helpers.fixtures``). The base URL is injected into the
environment by the runner, so the client is constructed with no arguments.
"""

import pytest

from test_helpers import (
    ENVIRONMENTAL_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    HYDROLOGY_OFFICER_HEADERS,
    RECLAMATION_OPERATOR_HEADERS,
    REGIONAL_DIRECTOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture()
def admin_headers():
    return SYSTEM_ADMIN_HEADERS


@pytest.fixture()
def operator_headers():
    return RECLAMATION_OPERATOR_HEADERS


@pytest.fixture()
def hydrology_headers():
    return HYDROLOGY_OFFICER_HEADERS


@pytest.fixture()
def env_headers():
    return ENVIRONMENTAL_OFFICER_HEADERS


@pytest.fixture()
def finance_headers():
    return FINANCE_OFFICER_HEADERS


@pytest.fixture()
def director_headers():
    return REGIONAL_DIRECTOR_HEADERS
