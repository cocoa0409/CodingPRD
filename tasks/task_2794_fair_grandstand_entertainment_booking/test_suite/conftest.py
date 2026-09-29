"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    BOX_OFFICE_MANAGER_HEADERS,
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SETTLEMENT_CONTROLLER_ALT_HEADERS,
    SETTLEMENT_CONTROLLER_HEADERS,
    SPONSORSHIP_DIRECTOR_HEADERS,
    TALENT_BUYER_ALT_HEADERS,
    TALENT_BUYER_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def talent_buyer_headers():
    return TALENT_BUYER_HEADERS


@pytest.fixture
def talent_buyer_alt_headers():
    return TALENT_BUYER_ALT_HEADERS


@pytest.fixture
def fair_operations_director_headers():
    return FAIR_OPERATIONS_DIRECTOR_HEADERS


@pytest.fixture
def production_manager_headers():
    return PRODUCTION_MANAGER_HEADERS


@pytest.fixture
def box_office_manager_headers():
    return BOX_OFFICE_MANAGER_HEADERS


@pytest.fixture
def sponsorship_director_headers():
    return SPONSORSHIP_DIRECTOR_HEADERS


@pytest.fixture
def settlement_controller_headers():
    return SETTLEMENT_CONTROLLER_HEADERS


@pytest.fixture
def settlement_controller_alt_headers():
    return SETTLEMENT_CONTROLLER_ALT_HEADERS
