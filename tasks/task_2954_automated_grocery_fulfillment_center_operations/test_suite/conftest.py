"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client
from test_helpers.test_users import (
    make_customer_headers as _make_customer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin"]


@pytest.fixture
def wave_planner_headers():
    return TEST_USERS["wave_planner"]


@pytest.fixture
def second_wave_planner_headers():
    """A second planner, needed wherever segregation of duties applies."""
    return TEST_USERS["wave_planner_2"]


@pytest.fixture
def pick_operator_headers():
    return TEST_USERS["pick_operator"]


@pytest.fixture
def second_pick_operator_headers():
    return TEST_USERS["pick_operator_2"]


@pytest.fixture
def grid_engineer_headers():
    return TEST_USERS["grid_engineer"]


@pytest.fixture
def unknown_customer_headers():
    """A shopper identifier that resolves to no customer account."""
    return TEST_USERS["unknown_customer"]


@pytest.fixture
def make_customer_headers():
    """Factory returning shopper headers for a given customer account id."""
    return _make_customer_headers
